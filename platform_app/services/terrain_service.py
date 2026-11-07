"""Simulated terrain-model outputs and explicit planner policy."""
TERRAIN_TYPES = [
    {'id':'road','name':'平整道路','probability':.98,'action':'正常通行','multiplier':1,'color':'#c9c2ac'},
    {'id':'grass','name':'草地','probability':.85,'action':'可以通行','multiplier':1,'color':'#9cb898','bounds':[10,65,35,90]},
    {'id':'gravel','name':'碎石坡','probability':.42,'action':'增加路径代价','multiplier':3.32,'color':'#b99e80','bounds':[65,15,90,35]},
    {'id':'water','name':'深水区域','probability':.02,'action':'禁止通行','multiplier':None,'color':'#7da9bc','bounds':[15,25,25,32]},
]


def terrain_at(x,y):
    for item in reversed(TERRAIN_TYPES[1:]):
        a,b,c,d=item['bounds']
        if a<=x<=c and b<=y<=d:return item
    return TERRAIN_TYPES[0]


def traversal_cost(x,y):
    return terrain_at(x,y)['multiplier'] or float('inf')
