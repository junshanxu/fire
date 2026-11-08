"""Measured Gazebo feedback; RMF ground routes and independent UAV controllers."""
import json, math, time
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist, PoseStamped
from nav_msgs.msg import Odometry
from std_msgs.msg import String
from rmf_fleet_msgs.msg import RobotState, RobotMode, Location, PathRequest
from fleet_config import DEVICES, CELLS

def wrap(a): return math.atan2(math.sin(a),math.cos(a))
def clamp(a,lo,hi): return max(lo,min(hi,a))

class Controllers(Node):
    def __init__(self):
        super().__init__("airport_motion_controller")
        self.poses={};self.paths={};self.path_ids={};self.airs={};self.arrived={};self.seen=set()
        self.cmd={};self.target={};self.seq=0;self.blocked={}
        for name,d in DEVICES.items():
            ns=d.get("namespace")
            if ns:self.create_subscription(Odometry,"/"+ns+"/odom",lambda m,n=name:self.odom(n,m),10)
            if d["type"]=="dog":
                self.paths[name]=[];self.path_ids[name]=""
                self.cmd[name]=self.create_publisher(Twist,"/"+ns+"/cmd_vel",10)
            if d["type"]=="drone":
                self.airs[name]={"id":"","status":"idle","index":0,"route":[],"label":"起降坪待命"}
                self.target[name]=self.create_publisher(PoseStamped,"/"+ns+"/target",10)
        self.create_subscription(PathRequest,"/robot_path_requests",self.route,10)
        self.create_subscription(RobotState,"/robot_state",self.robot,10)
        self.create_subscription(String,"/airport/air_command",self.air_command,10)
        self.robot_pub=self.create_publisher(RobotState,"/robot_state",10)
        self.status_pub=self.create_publisher(String,"/airport/agents",10)
        self.create_timer(.1,self.tick);self.create_timer(.3,self.publish)
    def now(self):return self.get_clock().now().nanoseconds/1e9
    def odom(self,name,m):
        p=m.pose.pose.position;q=m.pose.pose.orientation;v=m.twist.twist.linear
        self.poses[name]={"x":p.x,"y":p.y,"z":p.z,"yaw":math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z)),
            "speed":math.sqrt(v.x*v.x+v.y*v.y+v.z*v.z),"angular_speed":m.twist.twist.angular.z,
            "received":time.time(),"source":"gazebo_odometry"}
    def robot(self,m):
        if m.name not in DEVICES or DEVICES[m.name]["type"]!="amr":return
        now=m.location.t.sec+m.location.t.nanosec/1e9
        old=self.poses.get(m.name,{});dt=now-old.get("sample_time",now);speed=old.get("speed",0.);turn=0.
        if dt>0:
            speed=math.hypot(m.location.x-old.get("x",m.location.x),m.location.y-old.get("y",m.location.y))/dt
            turn=wrap(m.location.yaw-old.get("yaw",m.location.yaw))/dt
        self.poses[m.name]={"x":m.location.x,"y":m.location.y,"z":.15,"yaw":m.location.yaw,"speed":speed,"angular_speed":turn,
            "sample_time":now,"received":time.time(),"source":"gazebo_robot_state","mode":m.mode.mode,"task_id":m.task_id}
    def route(self,m):
        n=m.robot_name
        if m.fleet_name!="inspectionDog" or n not in self.paths or m.task_id==self.path_ids[n]:return
        self.path_ids[n]=m.task_id;self.paths[n]=list(m.path[1:]) if len(m.path)>1 else list(m.path)
    def air_command(self,m):
        try:
            d=json.loads(m.data);key=d["id"];n=d["device"]
            if n not in self.airs or key in self.seen or self.airs[n]["status"]=="running" or n not in self.poses:return
            cell=next(c for c in CELLS if c["drone"]==n);x,y,z=DEVICES[n]["home"];alt=cell["altitude"]
            if d["action"]!="survey":return
            route=[(x,y,alt,"起飞至 "+str(int(alt))+" 米"),
                   (cell["x"],cell["y"]+1.,alt,cell["id"]+"区上空定点复核"),
                   (x,y,alt,"复核完成，返航"),(x,y,z,"降落至本机起降坪")]
            self.seen.add(key);self.airs[n]={"id":key,"status":"running","index":0,"route":route,"label":route[0][3],"verified":False}
            self.arrived[n]=None
        except (ValueError,KeyError,TypeError,StopIteration):pass
    def tick(self):
        for n,path in self.paths.items():
            v=Twist();p=self.poses.get(n);self.blocked[n]=""
            if p and time.time()-p["received"]<2 and path:
                t=path[0];dist=math.hypot(t.x-p["x"],t.y-p["y"]);angle=wrap(math.atan2(t.y-p["y"],t.x-p["x"])-p["yaw"])
                if dist>.10:
                    v.angular.z=clamp(angle*2,-.8,.8)
                    if abs(angle)<.30:v.linear.x=min(.8,dist*1.8)*max(0,math.cos(angle))
                else:
                    v.angular.z=clamp(wrap(t.yaw-p["yaw"])*2,-.8,.8)
                    if abs(wrap(t.yaw-p["yaw"]))<.06:path.pop(0)
                # Defensive separation stop; RMF owns planned route coordination.
                for other,q in self.poses.items():
                    if other==n or DEVICES[other]["type"]=="drone" or time.time()-q["received"]>2:continue
                    dist2=math.hypot(q["x"]-p["x"],q["y"]-p["y"])
                    ahead=abs(wrap(math.atan2(q["y"]-p["y"],q["x"]-p["x"])-p["yaw"]))<1.2
                    if dist2<.85 and ahead:v.linear.x=0.;self.blocked[n]="前方设备距离不足，等待让行"
            self.cmd[n].publish(v)
        for n,a in self.airs.items():
            p=self.poses.get(n)
            if a["status"]!="running" or not p or time.time()-p["received"]>2:continue
            x,y,z,label=a["route"][a["index"]];a["label"]=label
            msg=PoseStamped();msg.header.frame_id="world";msg.header.stamp=self.get_clock().now().to_msg()
            msg.pose.position.x=float(x);msg.pose.position.y=float(y);msg.pose.position.z=float(z);msg.pose.orientation.w=1.;self.target[n].publish(msg)
            err=math.sqrt((x-p["x"])**2+(y-p["y"])**2+(z-p["z"])**2);a["error_m"]=err
            if err<.22 and p["speed"]<.25:
                if self.arrived[n] is None:self.arrived[n]=self.now()
                dwell=3. if a["index"]==1 else 1.
                if self.now()-self.arrived[n]>dwell:
                    if a["index"]==1:a["verified"]=True;a["verified_at"]=self.now()
                    a["index"]+=1;self.arrived[n]=None
                    if a["index"]>=len(a["route"]):a["status"]="completed";a["label"]="已降落，复核记录已提交"
            else:self.arrived[n]=None
    def publish(self):
        for n,path in self.paths.items():
            p=self.poses.get(n)
            if not p or time.time()-p["received"]>2:continue
            m=RobotState();m.name=n;m.model="SimplifiedQuadruped";m.task_id=self.path_ids[n];m.seq=self.seq;self.seq+=1
            m.battery_percent=100.;m.mode.mode=RobotMode.MODE_MOVING if path else RobotMode.MODE_IDLE
            m.location=Location();m.location.t=self.get_clock().now().to_msg();m.location.x=p["x"];m.location.y=p["y"];m.location.yaw=p["yaw"];m.location.level_name="L1";m.path=path.copy()
            self.robot_pub.publish(m)
        dogs={n:{"path_id":self.path_ids[n],"path_remaining":len(path),"blocked":self.blocked.get(n,""),
                  "target":[path[0].x,path[0].y] if path else None} for n,path in self.paths.items()}
        self.status_pub.publish(String(data=json.dumps({"poses":self.poses,"airs":self.airs,"dogs":dogs})))

if __name__=="__main__":
    rclpy.init();node=Controllers()
    try:rclpy.spin(node)
    finally:node.destroy_node();rclpy.shutdown()
