"""Session-only fly appearance, Blender 4.2.2. Original rig and source are read-only.

Run with Blender --background --factory-startup --python this_file.py.
Body mesh pivots are copied from the original blend. Leg meshes use the existing
Unity mapper's local +Z [0,1] segment convention. No armature is created.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import random
import sys

import bpy
from mathutils import Vector, Matrix

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DEST = REPO / 'UnityProject/Assets/FlyVisual/SessionRealism'
EVIDENCE = REPO / 'artifacts/sessions/01a09446-1c64-74c1-8579-f133826d2dd2'
MATERIAL_NAMES = ['ChitinGold', 'AbdomenDark', 'EyeRuby', 'WingMembrane', 'WingVein', 'Bristle']
sys.path.insert(0, str(HERE))
RNG = random.Random(43)


def xyz(p):
    """Unity right/up/forward -> Blender right/back/up."""
    return Vector((p[0], -p[2], p[1]))


class Geometry:
    def __init__(self):
        self.vertices, self.faces, self.uvs = [], [], []

    def patch(self, vertices, faces, uvs):
        start = len(self.vertices)
        self.vertices.extend(vertices)
        self.uvs.extend(uvs)
        self.faces.extend(tuple(start + i for i in f) for f in faces)

    def object(self, name, material, matrix=None):
        matrix = matrix or Matrix.Identity(4)
        inv = matrix.inverted()
        mesh = bpy.data.meshes.new(name + '_Mesh')
        mesh.from_pydata([inv @ xyz(v) for v in self.vertices], [], self.faces)
        mesh.update()
        uv = mesh.uv_layers.new(name='UVMap')
        for p in mesh.polygons:
            p.use_smooth = True
            for li in p.loop_indices:
                uv.data[li].uv = self.uvs[mesh.loops[li].vertex_index]
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.collection.objects.link(obj)
        obj.matrix_world = matrix
        mesh.materials.append(material)
        return obj


def ellipsoid(g, center, radius, segments=48, rings=28, vrange=(.04, .44), tilt=0):
    verts, uvs, faces = [], [], []
    for j in range(rings + 1):
        t = j / rings
        phi = math.pi * t
        for i in range(segments + 1):
            u = i / segments
            a = 2 * math.pi * u
            x = radius[0] * math.sin(phi) * math.cos(a)
            y = radius[1] * math.sin(phi) * math.sin(a)
            z = radius[2] * math.cos(phi)
            # Tilt only the mesh, never a rig transform.
            y, z = y * math.cos(tilt) - z * math.sin(tilt), y * math.sin(tilt) + z * math.cos(tilt)
            verts.append((center[0] + x, center[1] + y, center[2] + z))
            uvs.append((u, vrange[0] + t * (vrange[1] - vrange[0])))
    stride = segments + 1
    for j in range(rings):
        for i in range(segments):
            a = j * stride + i
            # Unity->Blender mapping is a rotation, so retain outward winding.
            faces.append((a, a + stride, a + stride + 1, a + 1))
    g.patch(verts, faces, uvs)


def tube(g, points, radii, sides=5, cap=True):
    points = [Vector(p) for p in points]
    verts, faces, uv = [], [], []
    for j, p in enumerate(points):
        axis = (points[min(j + 1, len(points) - 1)] - points[max(0, j - 1)]).normalized()
        reference = Vector((0, 1, 0)) if abs(axis.y) < .9 else Vector((1, 0, 0))
        bx = axis.cross(reference).normalized()
        by = axis.cross(bx).normalized()
        radius = radii[j] if isinstance(radii, (list, tuple)) else radii
        for k in range(sides):
            a = math.tau * k / sides
            verts.append(p + radius * (math.cos(a) * bx + math.sin(a) * by))
            uv.append((k / sides, .06 + .35 * j / max(1, len(points) - 1)))
    for j in range(len(points) - 1):
        for k in range(sides):
            a = j * sides + k
            b = j * sides + (k + 1) % sides
            faces.append((a, b, b + sides, a + sides))
    if cap:
        faces.append(tuple(reversed(range(sides))))
        faces.append(tuple((len(points) - 1) * sides + k for k in range(sides)))
    g.patch(verts, faces, uv)


def spline(points, steps=6, closed=False):
    pts = [Vector(p) for p in points]
    result = []
    for i in range(len(pts) if closed else len(pts) - 1):
        p0 = pts[(i - 1) % len(pts)] if closed else pts[max(0, i - 1)]
        p1, p2 = pts[i], pts[(i + 1) % len(pts)]
        p3 = pts[(i + 2) % len(pts)] if closed else pts[min(len(pts) - 1, i + 2)]
        for n in range(steps):
            t = n / steps
            result.append(.5 * ((2 * p1) + (-p0 + p2) * t +
                          (2 * p0 - 5 * p1 + 4 * p2 - p3) * t*t +
                          (-p0 + 3 * p1 - 3 * p2 + p3) * t*t*t))
    result.append(result[0] if closed else pts[-1])
    return result


def bristle(g, p, direction, length, radius, sides=3):
    p, direction = Vector(p), Vector(direction).normalized()
    tip = p + direction * length
    mid = p + direction * length * .6 + Vector((0, .004, -.005))
    tube(g, [p, mid, tip], [radius, radius * .52, radius * .035], sides)


def make_material(name):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get('Principled BSDF')
    bsdf.inputs['Metallic'].default_value = 0
    bsdf.inputs['Roughness'].default_value = .65
    prefix = {'ChitinGold': 'Body', 'AbdomenDark': 'Body', 'EyeRuby': 'Eye', 'WingMembrane': 'Wing'}.get(name)
    if prefix:
        color = nodes.new('ShaderNodeTexImage')
        color.image = bpy.data.images.load(str(DEST / 'Textures' / (prefix + '_BaseColor.png')), check_existing=True)
        color.label = 'Base color / wing opacity'
        if name == 'AbdomenDark':
            mult = nodes.new('ShaderNodeMixRGB')
            mult.blend_type = 'MULTIPLY'
            mult.inputs[0].default_value = 1
            mult.inputs[2].default_value = (.23, .18, .12, 1)
            links.new(color.outputs['Color'], mult.inputs[1])
            links.new(mult.outputs[0], bsdf.inputs['Base Color'])
        else:
            links.new(color.outputs['Color'], bsdf.inputs['Base Color'])
        normal = nodes.new('ShaderNodeTexImage')
        normal.image = bpy.data.images.load(str(DEST / 'Textures' / (prefix + '_Normal.png')), check_existing=True)
        normal.image.colorspace_settings.name = 'Non-Color'
        norm = nodes.new('ShaderNodeNormalMap')
        links.new(normal.outputs['Color'], norm.inputs['Color'])
        links.new(norm.outputs['Normal'], bsdf.inputs['Normal'])
        mask = nodes.new('ShaderNodeTexImage')
        mask.image = bpy.data.images.load(str(DEST / 'Textures' / (prefix + '_Mask.png')), check_existing=True)
        mask.image.colorspace_settings.name = 'Non-Color'
        rough = nodes.new('ShaderNodeMath')
        rough.operation = 'SUBTRACT'
        rough.inputs[0].default_value = 1
        links.new(mask.outputs['Alpha'], rough.inputs[1])
        links.new(rough.outputs[0], bsdf.inputs['Roughness'])
        if name == 'WingMembrane':
            links.new(color.outputs['Alpha'], bsdf.inputs['Alpha'])
            mat.surface_render_method = 'DITHERED'
    else:
        rgb = (.045, .025, .009, 1) if name == 'WingVein' else (.018, .010, .005, 1)
        bsdf.inputs['Base Color'].default_value = rgb
        bsdf.inputs['Roughness'].default_value = .72 if name == 'WingVein' else .82
    return mat


def body_geometry():
    groups = {n: Geometry() for n in MATERIAL_NAMES}
    ch, dark, eye, wing, vein, hair = (groups[n] for n in MATERIAL_NAMES)
    ellipsoid(ch, (0, 0, -.015), (.608, .407, .837), 64, 36)
    ellipsoid(ch, (0, .11, -.646), (.33, .235, .33), 48, 24)
    ellipsoid(ch, (0, .015, 1.015), (.495, .356, .345), 56, 32)
    # Cervical and thoracic plates stay attached to the original thorax pivot.
    ellipsoid(dark, (0, -.015, .746), (.265, .21, .16), 36, 20)
    for side in (-1, 1):
        ellipsoid(ch, (side*.456, -.115, .1), (.134, .188, .525), 40, 22)
        line = spline([(side*.28,.33,.49),(side*.38,.34,.13),(side*.39,.27,-.37),(side*.27,.28,-.62)], 8)
        tube(dark, line, .0028, 4)
    # Contiguous abdomen with shallow imbricated plates; pigment comes from atlas.
    profile = [(-.45,.32,.245),(-.68,.47,.31),(-.96,.532,.337),(-1.22,.514,.325),
               (-1.48,.426,.282),(-1.70,.303,.223),(-1.87,.153,.141),(-1.96,.008,.008)]
    verts, uvs, faces = [], [], []
    rings, around = 126, 72
    for j in range(rings + 1):
        t = j / rings
        z = -.45 - 1.51*t
        for k in range(len(profile)-1):
            if profile[k][0] >= z >= profile[k+1][0]:
                f = (z-profile[k][0])/(profile[k+1][0]-profile[k][0])
                rx = profile[k][1]*(1-f)+profile[k+1][1]*f
                ry = profile[k][2]*(1-f)+profile[k+1][2]*f
                break
        phase = (t*5.8) % 1
        plate = .008 * math.sin(math.pi*phase)**2
        for i in range(around + 1):
            u = i / around
            a = math.tau*u
            dorsal = max(0, math.sin(a))
            verts.append(((rx+plate*dorsal)*math.cos(a), -.04+(ry+plate*dorsal)*math.sin(a), z))
            uvs.append((u,.52+.46*t))
    for j in range(rings):
        for i in range(around):
            a=j*(around+1)+i
            faces.append((a,a+around+1,a+around+2,a+1))
    ch.patch(verts,faces,uvs)
    for side in (-1, 1):
        ellipsoid(eye, (side*.411,.102,1.139), (.236,.298,.254), 64, 40, (0,1), tilt=-.08)
        # Small rim under each eye, face, and compact proboscis.
        ellipsoid(ch,(side*.20,-.097,1.276),(.18,.18,.16),36,20)
        ellipsoid(ch,(side*.111,.046,1.345),(.06,.07,.062),28,16)
        ellipsoid(ch,(side*.154,-.009,1.426),(.050,.082,.087),32,20,tilt=.23)
        arista=spline([(side*.177,.026,1.483),(side*.26,.143,1.525),(side*.40,.316,1.525),(side*.49,.41,1.51)],6)
        tube(hair,arista,[.0044*(1-i/(len(arista)-1))+.00055 for i in range(len(arista))],4)
        for k in range(9):
            p=arista[3+k]
            for sign in (-1,1):
                bristle(hair,p,(side*.55,sign*.7,-.18),.032+(k%3)*.01,.0011)
        # Haltere's stalk and knob are separate shapes, rigidly thorax-bound.
        tube(ch,[(side*.47,-.09,-.52),(side*.59,-.05,-.64),(side*.656,.003,-.685)],[.024,.017,.020],8)
        ellipsoid(ch,(side*.674,.015,-.704),(.055,.052,.070),28,16)
    ellipsoid(dark,(0,-.205,1.245),(.121,.075,.12),32,18)
    for side in (-1,1):
        ellipsoid(ch,(side*.055,-.23,1.365),(.054,.06,.065),28,16)
    # Three restrained ocelli on the top of the head.
    for p in [(0,.341,1.03),(-.075,.325,.97),(.075,.325,.97)]:
        ellipsoid(dark,p,(.025,.017,.024),20,12)
    add_wings(wing,vein)
    # Dense short setae plus sparse directional macrochaetae, combined into one mesh.
    for n in range(380):
        a=RNG.uniform(0,math.tau)
        t=RNG.uniform(-.87,.88)
        if math.sin(a)<-.25: continue
        r=math.sqrt(1-t*t)
        p=Vector((.611*r*math.cos(a),.411*r*math.sin(a),.839*t-.015))
        normal=Vector((p.x/.608,p.y/.407,(p.z+.015)/.837)).normalized()
        direction=normal*.65+Vector((0,.22,-.7))
        bristle(hair,p,direction,RNG.uniform(.018,.042),RNG.uniform(.0010,.00165))
    for side in (-1,1):
        for z in (.5,.22,-.07,-.36):
            for x in (.19,.39):
                y=.407*math.sqrt(max(.01,1-(x/.608)**2-(z/.837)**2))
                bristle(hair,(side*x,y+.007,z),(side*.28,.8,-.65),.105 if x<.3 else .08,.0032,4)
        for x,y,z,d in [(.31,.276,1.08,(.35,.9,-.1)),(.26,.25,1.24,(.3,.8,.45)),(.1,.31,.95,(.1,.7,-.5))]:
            bristle(hair,(side*x,y,z),(side*d[0],d[1],d[2]),.13,.003,4)
        for k in range(55):
            a=RNG.uniform(.12,math.pi-.1)
            t=RNG.uniform(-.65,.65)
            r=math.sqrt(1-t*t)
            p=(side*(.28+.12*r*math.cos(a)),.345*r*math.sin(a),1.015+.3*t)
            bristle(hair,p,(side*.3,.75,-.25),.025,.0013)
    for n in range(150):
        t=RNG.uniform(.12,.87)
        z=-.45-1.51*t
        a=RNG.uniform(.05,math.pi-.05)
        for k in range(len(profile)-1):
            if profile[k][0]>=z>=profile[k+1][0]:
                f=(z-profile[k][0])/(profile[k+1][0]-profile[k][0])
                rx=profile[k][1]*(1-f)+profile[k+1][1]*f
                ry=profile[k][2]*(1-f)+profile[k+1][2]*f
                break
        p=((rx+.004)*math.cos(a),-.04+(ry+.005)*math.sin(a),z)
        bristle(hair,p,(math.cos(a)*.5,math.sin(a)*.6,-.85),RNG.uniform(.021,.038),.0012)
    return groups


def add_wings(wing,vein):
    for side in (-1,1):
        def p(x,y,z): return Vector((side*x,y,z))
        controls=[p(.36,.39,-.15),p(.57,.4,-.37),p(.88,.36,-.78),p(1.105,.302,-1.29),
                  p(1.135,.235,-1.85),p(1.013,.19,-2.25),p(.856,.188,-2.405),
                  p(.702,.239,-2.05),p(.48,.332,-1.18),p(.371,.387,-.43)]
        outline=spline(controls,10,True)[:-1]
        center=p(.755,.326,-1.272)
        verts=[center]; uv=[((abs(center.x)-.34)/.85,(-center.z-.15)/2.3)]; faces=[]
        # Concentric rings give a slight continuous camber instead of a flat fan.
        for ring in range(1,6):
            f=ring/5
            for q in outline:
                v=center.lerp(q,f)
                v.y+=.008*math.sin(math.pi*f)
                verts.append(v);uv.append(((abs(v.x)-.34)/.85,(-v.z-.15)/2.3))
        size=len(outline)
        for i in range(size):
            faces.append((0,1+i,1+(i+1)%size))
        for r in range(4):
            for i in range(size):
                a=1+r*size+i;b=1+r*size+(i+1)%size
                faces.append((a,a+size,b+size,b))
        if side<0: faces=[tuple(reversed(f)) for f in faces]
        wing.patch(verts,faces,uv)
        tube(vein,outline+[outline[0]],.0026,5)
        paths=[[(.36,.394,-.15),(.60,.396,-.59),(.88,.342,-1.14),(1.104,.257,-1.82)],
               [(.37,.393,-.18),(.57,.393,-.72),(.755,.332,-1.40),(.988,.2,-2.275)],
               [(.375,.394,-.22),(.535,.38,-.84),(.641,.325,-1.5),(.848,.194,-2.39)],
               [(.38,.387,-.27),(.452,.36,-.85),(.532,.30,-1.46),(.699,.247,-2.04)]]
        for points in paths:
            curve=spline([p(*q) for q in points],10)
            tube(vein,curve,[.0044*(1-i/(len(curve)-1))+.0011 for i in range(len(curve))],5)
        for points in [[(.59,.388,-.79),(.55,.38,-.86),(.464,.356,-.9)],
                       [(.831,.298,-1.63),(.715,.308,-1.71),(.587,.285,-1.73)]]:
            tube(vein,spline([p(*q) for q in points],6),.0022,5)


def leg_geometry(kind):
    ch,hair,dark=Geometry(),Geometry(),Geometry()
    profiles={
        'Bridge':[(0,.105),(.12,.119),(.32,.102),(.60,.077),(.84,.058),(1,.048)],
        'Coxa':[(0,.055),(.10,.068),(.29,.091),(.50,.087),(.75,.065),(.92,.047),(1,.040)],
        'Femur':[(0,.043),(.12,.066),(.29,.082),(.49,.077),(.73,.055),(.91,.038),(1,.033)],
        'Tibia':[(0,.034),(.10,.043),(.27,.040),(.42,.033),(.53,.027),(.59,.021)]}
    controls=profiles[kind]
    # Curvature is mesh-only, zero at both binding endpoints. Local Y mirrors
    # correctly across the current left/right mapper frames; no pivot is moved.
    bow={'Bridge':-.016,'Coxa':.023,'Femur':.032,'Tibia':.083}[kind]
    def center(z):
        return Vector((0,bow*math.sin(math.pi*z)**2,z))
    def radius(z):
        for i in range(len(controls)-1):
            if controls[i][0]<=z<=controls[i+1][0]:
                t=(z-controls[i][0])/(controls[i+1][0]-controls[i][0])
                t=t*t*(3-2*t)
                return controls[i][1]*(1-t)+controls[i+1][1]*t
        return controls[-1][1]
    def shell(start,end,radius_at,rings=32):
        verts,uv,faces=[],[],[]
        sides=20
        for j in range(rings+1):
            t=j/rings;z=start+(end-start)*t;p=center(z);r=radius_at(t,z)
            for k in range(sides+1):
                a=k/sides*math.tau
                # Restrained longitudinal cuticular ridges, not flat cylinders.
                rr=r*(1+.018*math.cos(a*8))
                verts.append(p+Vector((rr*math.cos(a),rr*.80*math.sin(a),0)))
                uv.append((k/sides,.065+.345*z))
        for j in range(rings):
            for k in range(sides):
                a=j*(sides+1)+k
                faces.append((a,a+1,a+sides+2,a+sides+1))
        faces.extend([tuple(reversed(range(sides))),tuple(rings*(sides+1)+k for k in range(sides))])
        ch.patch(verts,faces,uv)
    shell(0,controls[-1][0],lambda t,z:radius(z),48)
    # Chitin condyles soften the cut-off segment ends. These are rigid mesh
    # surfaces around the original joint, never additional movable bones.
    r0=controls[0][1]
    ellipsoid(ch,(0,0,.014),(r0*1.02,r0*.84,.039),24,14)
    if kind!='Tibia':
        r1=controls[-1][1]
        ellipsoid(ch,(0,0,.982),(r1*1.12,r1*.94,.039),24,14)
    if kind!='Bridge':
        count=44 if kind=='Femur' else 32
        end=.53 if kind=='Tibia' else .91
        for j in range(count):
            z=.09+(end-.09)*(j+.5)/count;r=radius(z);a=j*2.39996
            p=center(z)+Vector((r*math.cos(a),r*.81*math.sin(a),0))
            bristle(hair,p,(math.cos(a)*.7,math.sin(a)*.7,.45),
                    .023+.009*(j%3),.0013)
    if kind=='Tibia':
        # Five visible tarsomeres occupy the distal part of the existing final
        # segment. Their attachment remains rigid to that segment, including the
        # pretarsal claws at the unchanged FootContact endpoint.
        tarsus=[(.59,.768,.0205,.0158),(.774,.855,.0168,.0128),
                (.861,.916,.0135,.0101),(.922,.960,.011,.0082),(.966,1,.0091,.0058)]
        for index,(start,end,wide,narrow) in enumerate(tarsus):
            shell(start,end,lambda t,z,w=wide,n=narrow:(w*(1-t)+n*t)*(.90+.12*math.sin(math.pi*t)),12)
            if index:
                p=center(start-.003)
                ellipsoid(dark,p,(wide*.62,wide*.48,.007),16,8)
            for t in (.22,.68):
                z=start+(end-start)*t;p=center(z)
                for sign in (-1,1):
                    bristle(hair,p+Vector((sign*wide,0,0)),(sign*.8,-.2,.5),.023,.0011)
        for sign in (-1,1):
            claw=spline([(sign*.006,-.003,.983),(sign*.016,-.008,1.003),
                         (sign*.017,-.019,1.013),(sign*.010,-.021,1.009)],5)
            tube(dark,claw,[.0035*(1-i/(len(claw)-1))+.00025 for i in range(len(claw))],6)
            ellipsoid(ch,(sign*.008,-.009,.993),(.007,.005,.010),16,10)
    return {'ChitinGold':ch,'Bristle':hair,'AbdomenDark':dark}


def export(objects,path):
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects: obj.select_set(True)
    bpy.context.view_layer.objects.active=objects[0]
    bpy.ops.export_scene.fbx(filepath=str(path),use_selection=True,object_types={'MESH'},
                             axis_forward='-Z',axis_up='Y',apply_unit_scale=True,
                             bake_space_transform=True,add_leaf_bones=False,
                             bake_anim=False,path_mode='RELATIVE',use_mesh_modifiers=True)


def studio():
    scene=bpy.context.scene
    scene.render.engine='CYCLES'
    scene.cycles.samples=48
    scene.cycles.use_denoising=True
    scene.render.resolution_x=1600;scene.render.resolution_y=1200
    scene.render.resolution_percentage=100
    scene.world.use_nodes=True
    scene.world.node_tree.nodes['Background'].inputs[0].default_value=(.2,.2,.2,1)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value=.5
    def aim(obj,p): obj.rotation_euler=(xyz(p)-obj.location).to_track_quat('-Z','Y').to_euler()
    bpy.ops.object.camera_add(location=xyz((3.8,3.25,5.5)))
    cam=bpy.context.object;cam.name='Review_Camera';aim(cam,(0,0,-.35))
    cam.data.type='ORTHO';cam.data.ortho_scale=4.9;scene.camera=cam
    for name,loc,power,size in [('Key',(0,5,3),600,4),('Fill',(-4,2,0),360,3),('Rim',(1,3,-4),620,3)]:
        bpy.ops.object.light_add(type='AREA',location=xyz(loc))
        obj=bpy.context.object;obj.name='Review_'+name;obj.data.energy=power;obj.data.shape='DISK';obj.data.size=size;aim(obj,(0,0,-.3))
    scene.render.image_settings.file_format='PNG'
    return scene


def assemble_reference_pose(segments):
    """Display real serialized Unity pivots in Blender; never export this assembly."""
    layout = HERE/'rig_reference_pose.json'
    if not layout.exists():
        return False
    collection = bpy.data.collections.new('Assembled_Existing_Rig_ReferencePose')
    bpy.context.scene.collection.children.link(collection)
    conversion = Matrix(((1,0,0,0),(0,0,-1,0),(0,1,0,0),(0,0,0,1)))
    meshes = {o.name: o for o in segments}
    for binding in json.loads(layout.read_text())['bindings']:
        joint = binding['joint']
        if joint == 'Thorax': continue
        kind = 'Bridge' if joint.endswith('_ThoraxBridge') else joint.split('_')[-1]
        instance = meshes[kind].copy()
        instance.name = joint+'_ReferenceVisual'
        collection.objects.link(instance)
        values = binding['matrix']
        unity = Matrix([values[i:i+4] for i in range(0,16,4)])
        instance.matrix_world = conversion @ unity @ conversion.inverted()
    return True


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--skip-render',action='store_true')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    DEST.mkdir(parents=True,exist_ok=True);EVIDENCE.mkdir(parents=True,exist_ok=True)
    source=HERE.parent/'FlyVisual.blend'
    original_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    bpy.ops.wm.open_mainfile(filepath=str(source))
    pivots={n:bpy.data.objects[n].matrix_world.copy() for n in MATERIAL_NAMES}
    original_counts={n:len(bpy.data.objects[n].data.polygons) for n in MATERIAL_NAMES}
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
    for mat in list(bpy.data.materials): bpy.data.materials.remove(mat)
    from generate_surface_textures import generate
    generate(DEST/'Textures')
    materials={n:make_material(n) for n in MATERIAL_NAMES}
    groups=body_geometry()
    body=[groups[n].object(n,materials[n],pivots[n]) for n in MATERIAL_NAMES]
    export(body,DEST/'FlyVisual_Realism.fbx')
    segments=[]
    for name in ['Coxa','Femur','Tibia','Bridge']:
        meshes=[]
        for mat,g in leg_geometry(name).items():
            if g.vertices: meshes.append(g.object(name+'_'+mat,materials[mat]))
        bpy.ops.object.select_all(action='DESELECT')
        for obj in meshes: obj.select_set(True)
        bpy.context.view_layer.objects.active=meshes[0]
        bpy.ops.object.join()
        obj=bpy.context.object;obj.name=name;segments.append(obj)
    export(segments,DEST/'FlyLegSegments_Realism.fbx')
    # Keep the reusable segments editable in a dedicated collection, excluded from render.
    library=bpy.data.collections.new('Segment_Library_NOT_BODY');bpy.context.scene.collection.children.link(library)
    for obj in segments:
        for coll in list(obj.users_collection): coll.objects.unlink(obj)
        library.objects.link(obj)
    library.hide_render=True;library.hide_viewport=True
    counts={}
    for obj in body+segments:
        obj.data.calc_loop_triangles()
        counts[obj.name]={'vertices':len(obj.data.vertices),'triangles':len(obj.data.loop_triangles),'materials':[m.name for m in obj.data.materials]}
    full_body = assemble_reference_pose(segments)
    scene=studio()
    if full_body: scene.camera.data.ortho_scale=6.3
    for img in bpy.data.images:
        if img.source=='FILE': img.pack()
    bpy.ops.wm.save_as_mainfile(filepath=str(HERE/'FlyVisual_Realism.blend'))
    if not args.skip_render:
        scene.render.filepath=str(EVIDENCE/('blender-realism-full.png' if full_body else 'blender-realism-body.png'))
        bpy.ops.render.render(write_still=True)
    report={'blender':bpy.app.version_string,'seed':43,'sourceSha256':original_hash,
            'sourceUnchanged':hashlib.sha256(source.read_bytes()).hexdigest()==original_hash,
            'armatures':sum(o.type=='ARMATURE' for o in bpy.context.scene.objects),
            'bodyPivotsUnchanged':all(body[i].matrix_world==pivots[n] for i,n in enumerate(MATERIAL_NAMES)),
            'originalPolygons':original_counts,'meshes':counts,'assembledReferencePose':full_body}
    (EVIDENCE/'blender-generation.json').write_text(json.dumps(report,indent=2))
    print('FLY_REALISM_GENERATED',json.dumps(report))


if __name__=='__main__': main()
