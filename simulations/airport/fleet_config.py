"""Single source of truth for scene coordinates and fleet registration."""
CELLS=[]
DEVICES={}
for i,(zone,x,title,alarm,cargo) in enumerate([
    ('A',145.,'配电设备','模拟温升告警','绝缘检测工具箱'),
    ('B',135.,'行李输送','模拟振动告警','输送机维护工具箱'),
    ('C',125.,'安防设施','模拟设备离线','备用通信模块')]):
    suffix='' if i==0 else '_'+str(i+1)
    dog='inspection_dog'+suffix;drone='inspection_drone'+suffix
    dock='dog_dock'+suffix
    CELLS.append(dict(id=zone,name=zone+'区 · '+title,kind=alarm,x=x,y=-35.5,dog=dog,drone=drone,
        inspect='inspect_'+zone.lower(),delivery='delivery_'+zone.lower(),altitude=6.+i,cargo=cargo))
    DEVICES[dog]=dict(label='DOG-0'+str(i+1),type='dog',name='巡检机器狗',namespace='dog'+('' if i==0 else str(i+1)),
        home=[x+3.,-36.5,.62],dock=dock,fleet='inspectionDog',cell=zone)
    DEVICES[drone]=dict(label='UAV-0'+str(i+1),type='drone',name='复核无人机',namespace='drone'+('' if i==0 else str(i+1)),
        home=[x,-30.5,.40],cell=zone)
for i,x in enumerate([130.,133.]):
    DEVICES['logistics_'+str(i+1)]=dict(label='AMR-0'+str(i+1),type='amr',name='运输机器人',home=[x,-41.5,0.],
        dock='amr_dock'+('' if i==0 else '_2'),fleet='logistics')
POINTS=[(130.,-41.5,'amr_dock'),(133.,-41.5,'amr_dock_2'),(125.,-39.5,'lane_c'),(130.,-39.5,'lane_w'),
    (133.,-39.5,'lane_m'),(135.,-39.5,'lane_b'),(138.,-39.5,'lane_e'),(145.,-39.5,'lane_a'),(148.,-39.5,'lane_end')]
EDGES=[(0,3),(1,4),(2,3),(3,4),(4,5),(5,6),(6,7),(7,8)]
for cell in CELLS:
    dev=DEVICES[cell['dog']];base=len(POINTS)
    POINTS += [(dev['home'][0],dev['home'][1],dev['dock']),
        (cell['x'],cell['y'],cell['inspect']),(cell['x'],-38.,cell['delivery'])]
    EDGES += [(base,{'A':8,'B':6,'C':3}[cell['id']]),(base,base+1),(base+2,{'A':7,'B':5,'C':2}[cell['id']])]
LOCATIONS={n:[x,y] for x,y,n in POINTS}
CAMERA=dict(position=[137.,-60.,22.],pitch=.80,yaw=1.57,width=960,height=540,hfov=1.1)
