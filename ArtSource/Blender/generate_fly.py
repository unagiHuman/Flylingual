"""Original procedural display sculpture. Blender 4.2; no downloads or dependencies.
Coordinates are authored in Unity units (+Z forward, +Y up) then mapped to Blender.
"""
import bpy, math, random
from pathlib import Path
from mathutils import Vector

OUT = Path(__file__).resolve().parent
REPO = OUT.parent.parent
random.seed(43)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

def coord(p): return Vector((p[0], -p[2], p[1]))
def material(name, rgb, rough=.4, metallic=0, alpha=1):
    m=bpy.data.materials.new(name); m.diffuse_color=(*rgb,alpha); m.use_nodes=True
    s=next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'); s.inputs['Base Color'].default_value=(*rgb,1)
    s.inputs['Roughness'].default_value=rough; s.inputs['Metallic'].default_value=metallic
    s.inputs['Alpha'].default_value=alpha
    if alpha < 1: m.surface_render_method='DITHERED'
    return m
gold=material('ChitinGold',(.34,.19,.055),.34,.15)
dark=material('AbdomenDark',(.057,.029,.014),.39)
eye=material('EyeRuby',(.53,.014,.024),.29,.05)
wing=material('WingMembrane',(.66,.78,.77),.24,.08,.29)
vein=material('WingVein',(.23,.26,.19),.4)
hair=material('Bristle',(.031,.022,.013),.7)
objects=[]
def finish(obj,name,mat):
    obj.name=name; obj.data.materials.append(mat); objects.append(obj)
    if obj.type=='MESH':
        for p in obj.data.polygons:p.use_smooth=True
    return obj
def ellipsoid(name,loc,size,mat,segments=40,rings=24):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=segments,ring_count=rings,location=coord(loc))
    o=bpy.context.object; o.scale=(size[0],size[2],size[1]); return finish(o,name,mat)
def line(name,pts,radius,mat):
    c=bpy.data.curves.new(name,'CURVE'); c.dimensions='3D'; c.bevel_depth=radius; c.bevel_resolution=2
    s=c.splines.new('POLY'); s.points.add(len(pts)-1)
    for v,p in zip(s.points,pts):v.co=(*coord(p),1)
    o=bpy.data.objects.new(name,c); bpy.context.collection.objects.link(o)
    return finish(o,name,mat)

ellipsoid('Thorax',(0,0,0),(.62,.42,.86),gold)
ellipsoid('Scutellum',(0,.16,-.64),(.37,.28,.34),gold)
ellipsoid('Head',(0,.04,1.04),(.53,.39,.38),gold)
ellipsoid('Abdomen',(0,-.02,-1.11),(.54,.35,.88),gold)
# Dark posterior cap and layered tergite bands (explicit geometry survives FBX).
ellipsoid('PosteriorCap',(0,-.03,-1.67),(.31,.24,.36),dark)
for i,z in enumerate([-.72,-.94,-1.18,-1.43]):
    t=(z+1.11)/.88; rx=.55*math.sqrt(1-t*t); ry=.36*math.sqrt(1-t*t)
    pts=[(rx*math.cos(a),-.02+ry*math.sin(a),z) for a in [j*math.pi/48 for j in range(97)]]
    line('TergiteBand_%02d'%i,pts,.037,dark)
for side in [-1,1]:
    # Fine contiguous eye facets; no protruding bead-like spheres.
    o=ellipsoid('CompoundEye_'+str(side),(side*.405,.115,1.17),(.225,.30,.25),eye,64,40)
    for poly in o.data.polygons: poly.use_smooth=False
    ellipsoid('AntennaBase_'+str(side),(side*.14,.07,1.43),(.065,.075,.1),gold)
    ellipsoid('AntennaClub_'+str(side),(side*.20,.025,1.55),(.065,.09,.12),gold)
    line('Arista_'+str(side),[(side*.22,.06,1.58),(side*.36,.28,1.65),(side*.50,.40,1.65)],.008,hair)
    for k in range(4):
        a=(side*(.28+k*.042),.14+k*.045,1.63)
        line('AristaBranch',[a,(a[0]+side*.07,a[1]+.06,a[2]-.04)],.0035,hair)
    ellipsoid('Haltere_'+str(side),(side*.59,.0,-.58),(.07,.065,.075),gold)
    # Two narrow, swept resting wings with explicit vein graph.
    base=(side*.36,.39,-.15)
    outline=[base,(side*.68,.42,-.42),(side*1.06,.37,-1.0),(side*1.18,.28,-1.65),(side*1.07,.20,-2.27),(side*.84,.18,-2.45),(side*.61,.25,-1.84),(side*.43,.33,-.82)]
    center=(side*.77,.31,-1.30)
    verts=[coord(center)]+[coord(p) for p in outline]
    mesh=bpy.data.meshes.new('WingMesh'); mesh.from_pydata(verts,[],[(0,i+1,(i+1)%len(outline)+1) for i in range(len(outline))]); mesh.update()
    o=bpy.data.objects.new('Wing_'+str(side),mesh); bpy.context.collection.objects.link(o); finish(o,o.name,wing)
    line('WingMargin_'+str(side),outline+[base],.009,vein)
    for n,end in enumerate(outline[3:7]):
        mid=(base[0]*.45+end[0]*.55,.355,base[2]*.45+end[2]*.55)
        line('LongitudinalVein_'+str(side)+'_'+str(n),[base,mid,end],.006,vein)
    line('CrossVein_'+str(side),[(side*.58,.36,-.85),(side*.83,.355,-1.0),(side*1.06,.37,-1.0)],.005,vein)
# Sparse bristles concentrated over thorax, avoiding opaque fuzz.
for i in range(95):
    a=random.uniform(0,math.tau); t=random.uniform(-.83,.83)
    p=Vector((.626*math.sqrt(1-t*t)*math.cos(a),.425*math.sqrt(1-t*t)*math.sin(a),.86*t))
    if p.y<-.05: continue
    n=Vector((p.x/.62,p.y/.42,p.z/.86)).normalized()
    tip=p+n*random.uniform(.065,.12)+Vector((0,0,-.03))
    line('ThoraxBristle_%03d'%i,[p,tip],.0035,hair)

# Merge meshes per material for a small runtime renderer count, preserving names.
for o in objects:
    if o.type=='CURVE':
        bpy.context.view_layer.objects.active=o; o.select_set(True)
        bpy.ops.object.convert(target='MESH'); o.select_set(False)
meshes=list(bpy.context.scene.objects)
for m in [gold,dark,eye,wing,vein,hair]:
    bpy.ops.object.select_all(action='DESELECT')
    group=[o for o in list(bpy.context.scene.objects) if o.type=='MESH' and o.data.materials and o.data.materials[0]==m]
    for o in group:o.select_set(True)
    bpy.context.view_layer.objects.active=group[0]; bpy.ops.object.join(); group[0].name=m.name
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
bpy.ops.export_scene.fbx(filepath=str(REPO/'UnityProject/Assets/FlyVisual/FlyVisual.fbx'),use_selection=True,object_types={'MESH'},axis_forward='-Z',axis_up='Y',apply_unit_scale=True,bake_space_transform=True,add_leaf_bones=False)

# Presentation-only studio, deliberately excluded from FBX.
scene=bpy.context.scene; scene.render.engine='CYCLES'; scene.cycles.samples=32
scene.render.resolution_x=1280; scene.render.resolution_y=960; scene.render.resolution_percentage=100
scene.world.color=(.055,.055,.055)
def point_at(o,p):o.rotation_euler=(coord(p)-o.location).to_track_quat('-Z','Y').to_euler()
bpy.ops.object.camera_add(location=coord((4,3.8,5.8))); cam=bpy.context.object; point_at(cam,(0,0,-.3)); scene.camera=cam; cam.data.type='ORTHO'; cam.data.ortho_scale=5.3
for loc,power,size,color in [((1,5,3),750,4,(1,.87,.66)),((-4,2,1),550,3,(.62,.80,1)),((1,2,-4),850,3,(.75,.9,1))]:
    bpy.ops.object.light_add(type='AREA',location=coord(loc)); o=bpy.context.object; o.data.energy=power; o.data.shape='DISK'; o.data.size=size; o.data.color=color; point_at(o,(0,0,-.3))
scene.render.image_settings.file_format='PNG'; scene.render.filepath=str(OUT/'FlyVisual_preview.png')
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'FlyVisual.blend'))
bpy.ops.render.render(write_still=True)
print('VISUAL_COMPLETE',len(bpy.data.meshes),'mesh datablocks')




