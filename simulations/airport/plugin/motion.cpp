// Ground base is planar with visual gait, not torque-controlled locomotion.
// UAV plant uses a gravity-compensating PD force controller, not PX4.
// All telemetry is measured from Gazebo, never inferred from commands.
#include <gazebo/gazebo.hh>
#include <gazebo/physics/physics.hh>
#include <gazebo/common/common.hh>
#include <gazebo_ros/node.hpp>
#include <geometry_msgs/msg/twist.hpp>
#include <geometry_msgs/msg/pose_stamped.hpp>
#include <nav_msgs/msg/odometry.hpp>
#include <mutex>
#include <algorithm>
#include <cmath>
namespace gazebo {
class AirportMotion : public ModelPlugin {
  physics::ModelPtr model_;
  physics::LinkPtr body_;
  gazebo_ros::Node::SharedPtr node_;
  event::ConnectionPtr update_;
  rclcpp::Subscription<geometry_msgs::msg::Twist>::SharedPtr cmd_;
  rclcpp::Subscription<geometry_msgs::msg::PoseStamped>::SharedPtr target_;
  rclcpp::Publisher<nav_msgs::msg::Odometry>::SharedPtr odom_;
  std::mutex mutex_;
  geometry_msgs::msg::Twist velocity_;
  ignition::math::Vector3d goal_;
  double yaw_goal_=0,last_=0,received_=-100;
  bool flying_=false;
 public:
  void Load(physics::ModelPtr model,sdf::ElementPtr sdf) override {
    model_=model; body_=model->GetLink("body");
    node_=gazebo_ros::Node::Get(sdf);
    flying_=sdf->Get<bool>("flying",false).first;
    goal_=model_->WorldPose().Pos();
    odom_=node_->create_publisher<nav_msgs::msg::Odometry>("odom",10);
    cmd_=node_->create_subscription<geometry_msgs::msg::Twist>("cmd_vel",10,
      [this](geometry_msgs::msg::Twist::SharedPtr m){
        std::lock_guard<std::mutex> g(mutex_);
        velocity_=*m; received_=model_->GetWorld()->SimTime().Double();
      });
    target_=node_->create_subscription<geometry_msgs::msg::PoseStamped>("target",10,
      [this](geometry_msgs::msg::PoseStamped::SharedPtr m){
        std::lock_guard<std::mutex> g(mutex_);
        goal_.Set(m->pose.position.x,m->pose.position.y,m->pose.position.z);
        auto q=m->pose.orientation;
        yaw_goal_=std::atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z));
        received_=model_->GetWorld()->SimTime().Double();
      });
    update_=event::Events::ConnectWorldUpdateBegin(std::bind(&AirportMotion::Step,this));
  }
  void Step(){
    std::lock_guard<std::mutex> g(mutex_);
    double now=model_->GetWorld()->SimTime().Double();
    auto pose=body_->WorldPose(); auto vel=body_->WorldLinearVel();
    double yaw=pose.Rot().Yaw();
    if(flying_){
      auto error=goal_-pose.Pos();
      double mass=body_->GetInertial()->Mass();
      body_->AddForce({mass*std::clamp(2*error.X()-2.8*vel.X(),-3.0,3.0),
        mass*std::clamp(2*error.Y()-2.8*vel.Y(),-3.0,3.0),
        mass*(9.81+std::clamp(3.5*error.Z()-3.8*vel.Z(),-5.0,5.0))});
      auto angles=pose.Rot().Euler(); auto omega=body_->WorldAngularVel();
      double dy=std::atan2(std::sin(yaw_goal_-yaw),std::cos(yaw_goal_-yaw));
      body_->AddTorque({-4*angles.X()-1.5*omega.X(),-4*angles.Y()-1.5*omega.Y(),
                        std::clamp(1.5*dy-0.8*omega.Z(),-1.0,1.0)});
      for(int i=0;i<4;i++){
        auto j=model_->GetJoint("rotor_joint_"+std::to_string(i));
        if(j) j->SetPosition(0,now*35*(i%2?-1:1));
      }
    }else{
      double speed=now-received_<0.7?velocity_.linear.x:0;
      double turn=now-received_<0.7?velocity_.angular.z:0;
      body_->SetLinearVel({std::cos(yaw)*speed,std::sin(yaw)*speed,0});
      body_->SetAngularVel({0,0,turn});
      for(int i=0;i<4;i++){
        double phase=now*8+(i==0||i==3?0:3.14159265);
        auto j=model_->GetJoint("hip_"+std::to_string(i));
        auto k=model_->GetJoint("knee_"+std::to_string(i));
        if(j) j->SetPosition(0,std::abs(speed)>0.03?0.4*std::sin(phase):0);
        if(k) k->SetPosition(0,-0.6+(std::abs(speed)>0.03?0.32*std::sin(phase+0.6):0));
      }
    }
    if(now-last_<0.1)return;
    last_=now;
    nav_msgs::msg::Odometry msg;
    msg.header.stamp=rclcpp::Time(static_cast<int64_t>(now*1e9));
    msg.header.frame_id="world";msg.child_frame_id=model_->GetName()+"/body";
    msg.pose.pose.position.x=pose.Pos().X();msg.pose.pose.position.y=pose.Pos().Y();msg.pose.pose.position.z=pose.Pos().Z();
    msg.pose.pose.orientation.x=pose.Rot().X();msg.pose.pose.orientation.y=pose.Rot().Y();
    msg.pose.pose.orientation.z=pose.Rot().Z();msg.pose.pose.orientation.w=pose.Rot().W();
    msg.twist.twist.linear.x=vel.X();msg.twist.twist.linear.y=vel.Y();msg.twist.twist.linear.z=vel.Z();
    msg.twist.twist.angular.z=body_->WorldAngularVel().Z();odom_->publish(msg);
  }
};
GZ_REGISTER_MODEL_PLUGIN(AirportMotion)
}
