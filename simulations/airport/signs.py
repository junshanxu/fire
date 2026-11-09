"""Add readable airport signage and seating to the official central concourse."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import xml.etree.ElementTree as E

def decorate(world, root):
    folder=root/"runtime"/"signs";folder.mkdir(exist_ok=True)
    font="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    def sign(name,x,y,z,width,height,title,subtitle,color):
        image=Image.new("RGB",(1200,240),(15,30,44));d=ImageDraw.Draw(image)
        d.rectangle((0,0,15,240),fill=color)
        d.text((45,32),title,font=ImageFont.truetype(font,60),fill=color)
        d.text((47,137),subtitle,font=ImageFont.truetype(font,27),fill=(220,234,244))
        image.save(folder/(name+".png"))
        (folder/(name+".material")).write_text("material Airport/"+name+"\n{\n technique\n {\n pass\n {\n lighting off\n texture_unit\n {\n texture "+name+".png\n }\n }\n }\n}\n")
        dae='''<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
<asset><unit name="meter" meter="1"/><up_axis>Z_UP</up_axis></asset>
<library_images><image id="image"><init_from>NAME.png</init_from></image></library_images>
<library_effects><effect id="effect"><profile_COMMON><newparam sid="surface"><surface type="2D"><init_from>image</init_from></surface></newparam><newparam sid="sampler"><sampler2D><source>surface</source></sampler2D></newparam><technique sid="common"><phong><diffuse><texture texture="sampler" texcoord="UVMap"/></diffuse></phong></technique></profile_COMMON></effect></library_effects>
<library_materials><material id="mat"><instance_effect url="#effect"/></material></library_materials>
<library_geometries><geometry id="quad"><mesh>
<source id="positions"><float_array id="positions-array" count="12">-0.5 0 0 0.5 0 0 0.5 0 1 -0.5 0 1</float_array><technique_common><accessor source="#positions-array" count="4" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>
<source id="uv"><float_array id="uv-array" count="8">0 0 1 0 1 1 0 1</float_array><technique_common><accessor source="#uv-array" count="4" stride="2"><param name="S" type="float"/><param name="T" type="float"/></accessor></technique_common></source>
<vertices id="vertices"><input semantic="POSITION" source="#positions"/></vertices>
<triangles material="mat" count="2"><input semantic="VERTEX" source="#vertices" offset="0"/><input semantic="TEXCOORD" source="#uv" offset="1" set="0"/><p>0 0 1 1 2 2 0 0 2 2 3 3</p></triangles>
</mesh></geometry></library_geometries>
<library_visual_scenes><visual_scene id="scene"><node id="sign"><instance_geometry url="#quad"><bind_material><technique_common><instance_material symbol="mat" target="#mat"><bind_vertex_input semantic="UVMap" input_semantic="TEXCOORD" input_set="0"/></instance_material></technique_common></bind_material></instance_geometry></node></visual_scene></library_visual_scenes>
<scene><instance_visual_scene url="#scene"/></scene></COLLADA>'''
        (folder/(name+".dae")).write_text(dae.replace("NAME",name))
        model=E.fromstring('<model name="'+name+'"><static>true</static><pose>'+f"{x} {y} {z} 0 0 0"+'</pose><link name="body"><visual name="text"><geometry><mesh><uri>file:///opt/airport/runtime/signs/'+name+'.dae</uri><scale>'+f"{width} 1 {height}"+'</scale></mesh></geometry></visual></link></model>')
        world.append(model)
        mat=E.SubElement(model.find(".//visual"),"material")
        script=E.SubElement(mat,"script")
        E.SubElement(script,"uri").text="file:///opt/airport/runtime/signs"
        E.SubElement(script,"name").text="Airport/"+name
        E.SubElement(mat,"lighting").text="false"
    sign("departures",138,-29,3.3,12,2.4,"T1  |  DEPARTURES","GATES A01 - A04      /      CENTRAL CONCOURSE",(185,235,113))
    sign("dog_service",145,-33.3,1.9,4.6,.8,"A / POWER","ELECTRICAL EQUIPMENT",(244,196,103))
    sign("air_service",135,-33.3,1.9,4.6,.8,"B / BAGGAGE","CONVEYOR MAINTENANCE",(96,222,199))
    sign("amr_service",125,-33.3,1.9,4.6,.8,"C / SECURITY","COMMUNICATION SYSTEM",(124,180,255))
    sign("logistics",132,-44,1.8,6.2,1.0,"SERVICE LOGISTICS","2 AMRs / 3 WORK ORDERS",(124,180,255))
    # Seats stay outside all demonstrated traffic paths.
    for i in range(4):
        x=128.5+2.8*i
        for j in range(3):
            seat=E.fromstring(f'''<model name="central_seat_{i}_{j}"><static>true</static><pose>{x+j*.66} -27 0 0 0 0</pose><link name="body">
<visual name="seat"><pose>0 0 .45 0 0 0</pose><geometry><box><size>.58 .58 .09</size></box></geometry><material><ambient>.20 .31 .42 1</ambient><diffuse>.20 .31 .42 1</diffuse></material></visual>
<visual name="back"><pose>0 .25 .79 .12 0 0</pose><geometry><box><size>.58 .08 .6</size></box></geometry><material><ambient>.20 .31 .42 1</ambient><diffuse>.20 .31 .42 1</diffuse></material></visual>
<visual name="leg"><pose>0 0 .22 0 0 0</pose><geometry><box><size>.05 .40 .44</size></box></geometry><material><diffuse>.6 .65 .7 1</diffuse></material></visual>
</link></model>''')
            world.append(seat)
