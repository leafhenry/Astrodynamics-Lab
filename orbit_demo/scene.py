"""OSG scene graph, embedded into the Qt-owned OpenGL context.

This is a Python implementation of the osgQt embedding pattern, not a
binding to the historical C++ osgQt library. OSG performs all 3D rendering.
"""
import math
import os
import time
from pathlib import Path
import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtOpenGLWidgets import QOpenGLWidget

os.environ.setdefault("OSG_THREADING", "SingleThreaded")
from OpenSceneGraph import osg, osgViewer, osgDB
from OpenSceneGraph.GL import GL_DEPTH_TEST, GL_PROGRAM_POINT_SIZE
from .mechanics import EARTH_RADIUS
from .environment import solar_position, earth_rotation, eclipse, shadow_outline
from .resources import GridSettings,is_sgp4
from .station_labels import StationLabels

VERTEX = """#version 330 core
in vec4 osg_Vertex;
uniform mat4 osg_ModelViewProjectionMatrix;
out vec3 localPosition;
void main() {
    localPosition = osg_Vertex.xyz;
    gl_Position = osg_ModelViewProjectionMatrix * osg_Vertex;
}
"""
FLAT = """#version 330 core
uniform vec3 tint;
out vec4 fragColor;
void main() { fragColor = vec4(tint, 1.0); }
"""
GLOBE = """#version 330 core
in vec3 localPosition;
uniform sampler2D earthMap;
uniform vec3 sunDirection;
uniform vec3 eyePosition;
uniform float earthAngle;
uniform float showGraticule;
uniform float gridSpacing;
uniform float gridWidth;
uniform vec3 gridColor;
uniform float emphasizeEquator;
out vec4 fragColor;
void main() {
    vec3 n = normalize(localPosition);
    vec2 uv = vec2((atan(n.y,n.x)-earthAngle)/6.28318530718+.5,
                   asin(clamp(n.z,-1.0,1.0))/3.14159265359+.5);
    vec3 albedo = pow(texture(earthMap,uv).rgb,vec3(2.2));
    float incidence = dot(n,sunDirection);
    float day = max(incidence,0.0);
    float daySide = smoothstep(-.018,.018,incidence);
    vec3 color = albedo*(.05+.25*daySide+.85*day);
    vec3 viewDir = normalize(eyePosition-localPosition);
    float rim = pow(1.0-max(dot(n,viewDir),0.0),4.0);
    color += vec3(.015,.07,.17)*rim*smoothstep(-.12,.3,incidence);
    vec3 displayColor = pow(color,vec3(1.0/2.2));
    // Analytic geographic grid in the SAME rotating UV frame as the map.
    // Derivatives keep lines approximately one pixel wide when zooming.
    vec2 cells = (uv-vec2(.5))*vec2(360.0/gridSpacing,180.0/gridSpacing);
    vec2 distanceToLine = abs(fract(cells+.5)-.5);
    vec2 pixelDistance = distanceToLine/max(fwidth(cells),vec2(.0001))/gridWidth;
    float meridians = (1.0-smoothstep(.35,1.15,pixelDistance.x))*smoothstep(.01,.12,length(n.xy));
    float parallels = 1.0-smoothstep(.35,1.15,pixelDistance.y);
    float grid = max(meridians,parallels);
    float equator = emphasizeEquator*(1.0-smoothstep(.5,1.5,abs(cells.y)/max(fwidth(cells.y),.0001)/gridWidth));
    vec3 lineColor = mix(gridColor,vec3(.65,.85,.9),equator);
    displayColor = mix(displayColor,lineColor,showGraticule*max(grid*.48,equator*.65));
    // Pixel-scaled terminator: fixed on the surface and independent of grids.
    float boundaryDistance = abs(incidence)/max(fwidth(incidence),.00001);
    float boundary = 1.0-smoothstep(.65,1.55,boundaryDistance);
    displayColor = mix(displayColor,vec3(.953,.812,.529),boundary*.92);
    fragColor = vec4(displayColor,1.0);
}
"""
STAR_VERTEX = """#version 330 core
in vec4 osg_Vertex;
uniform mat4 osg_ModelViewProjectionMatrix;
out float brightness;
void main() {
    float seed = fract(sin(dot(osg_Vertex.xyz,vec3(12.9898,78.233,45.16)))*43758.5453);
    brightness = .28+.72*pow(seed,3.0);
    gl_PointSize = 1.0+2.4*pow(seed,6.0);
    gl_Position = osg_ModelViewProjectionMatrix*osg_Vertex;
}
"""
STAR_FRAGMENT = """#version 330 core
in float brightness;
out vec4 fragColor;
void main() {
    float radius = length(gl_PointCoord-vec2(.5))*2.0;
    if (radius>1.0) discard;
    fragColor = vec4(vec3(.78,.86,1.0)*brightness*(1.0-.5*radius),1.0);
}
"""

BATCH_VERTEX = """#version 330 core
in vec4 osg_Vertex;
in vec3 resourceColor;
uniform mat4 osg_ModelViewProjectionMatrix;
uniform float pointSize;
out vec3 batchColor;
void main() {
    batchColor = resourceColor;
    gl_PointSize = pointSize;
    gl_Position = osg_ModelViewProjectionMatrix*osg_Vertex;
}
"""
BATCH_FRAGMENT = """#version 330 core
in vec3 batchColor;
out vec4 fragColor;
void main() { fragColor = vec4(batchColor,1.0); }
"""
LINE_VERTEX = """#version 330 core
in vec4 osg_Vertex;
in vec3 resourceColor;
in float resourceWidth;
uniform mat4 osg_ModelViewProjectionMatrix;
out vec3 vertexColor;
out float vertexWidth;
void main() {
    vertexColor = resourceColor;
    vertexWidth = resourceWidth;
    gl_Position = osg_ModelViewProjectionMatrix*osg_Vertex;
}
"""
LINE_GEOMETRY = """#version 330 core
layout(lines) in;
layout(triangle_strip, max_vertices=4) out;
in vec3 vertexColor[];
in float vertexWidth[];
out vec3 batchColor;
uniform vec2 viewportSize;
uniform float pixelRatio;
void main() {
    vec4 a = gl_in[0].gl_Position, b = gl_in[1].gl_Position;
    if (a.w <= 0.0 || b.w <= 0.0) return;
    vec2 delta = (b.xy/b.w-a.xy/a.w)*viewportSize;
    vec2 normal = vec2(-delta.y,delta.x)/max(length(delta),0.001);
    vec2 offset = normal*vertexWidth[0]*pixelRatio/viewportSize;
    batchColor = vertexColor[0];
    gl_Position = a+vec4(offset*a.w,0,0); EmitVertex();
    gl_Position = a-vec4(offset*a.w,0,0); EmitVertex();
    batchColor = vertexColor[1];
    gl_Position = b+vec4(offset*b.w,0,0); EmitVertex();
    gl_Position = b-vec4(offset*b.w,0,0); EmitVertex();
    EndPrimitive();
}
"""


def line_program(node):
    program = osg.Program(shaders=(osg.Shader(osg.Shader.VERTEX,LINE_VERTEX),
        osg.Shader(osg.Shader.GEOMETRY,LINE_GEOMETRY),osg.Shader(osg.Shader.FRAGMENT,BATCH_FRAGMENT)))
    for name,index in [('osg_Vertex',0),('resourceColor',1),('resourceWidth',2)]:
        program.bindAttribLocation[name] = index
    node.stateSet.attributes.append(program)
    node.stateSet.uniforms['viewportSize'] = osg.Vec2(1,1)
    node.stateSet.uniforms['pixelRatio'] = 1.0


def geometry(points, mode, color, fragment=FLAT, vertex=VERTEX):
    points = np.asarray(points, dtype=np.float32).reshape(-1,3)
    array = osg.Vec3Array(points)
    geom = osg.Geometry()
    geom.vertexArray = array
    geom.vertexAttrib[0] = array
    geom.useVertexBufferObjects = True
    geom.primitiveSets.append(osg.DrawArrays(mode, 0, len(points)))
    node = osg.Geode()
    node.drawables.append(geom)
    node.cullingActive = False
    program = osg.Program(shaders=(osg.Shader(osg.Shader.VERTEX, vertex),
                                   osg.Shader(osg.Shader.FRAGMENT, fragment)))
    program.bindAttribLocation["osg_Vertex"] = 0
    if vertex == BATCH_VERTEX:
        program.bindAttribLocation["resourceColor"] = 1
    node.stateSet.attributes.append(program)
    node.stateSet.uniforms["tint"] = osg.Vec3(*color)
    node.stateSet.modes[GL_DEPTH_TEST] = osg.StateAttribute.ON
    return node


def sphere(radius=1, latitudes=48, longitudes=96):
    points = []
    def vertex(i, j):
        lat = -math.pi/2+math.pi*i/latitudes
        lon = 2*math.pi*j/longitudes
        return (radius*math.cos(lat)*math.cos(lon), radius*math.cos(lat)*math.sin(lon), radius*math.sin(lat))
    for i in range(latitudes):
        for j in range(longitudes):
            a, b, c, d = vertex(i,j), vertex(i,j+1), vertex(i+1,j+1), vertex(i+1,j)
            points.extend((a,b,c,a,c,d))
    return points


class OrbitView(QOpenGLWidget):
    render_failed = Signal(str)
    initialized = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.viewer = None
        self.ready = False
        self.render_error = None
        self.root = None
        self.elements = None
        self.seconds = 0.0
        self.yaw, self.pitch, self.distance = -65.0, 36.0, 9.0
        self._last_mouse = None
        self.show_grid = False
        self.show_velocity = False
        self.show_stars = True
        self.show_shadow = False
        self.show_sun = False
        self.show_graticule = True
        self.grid_settings = GridSettings()
        self.resources = []
        self.active_id = None
        self.batch_nodes = {}
        self.stations = []
        self.frame_count = 0
        self.frame_times = []
        self.resource_errors = {}
        self._orbit_bucket = None
        self._shadow_bucket = None
        self.setMinimumSize(480, 220)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.station_labels = StationLabels(self)

    def update(self,*args):
        super().update(*args)
        if hasattr(self,'station_labels'): self.station_labels.update()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.station_labels.setGeometry(self.rect())

    def camera_eye(self):
        yaw,pitch = math.radians(self.yaw),math.radians(self.pitch)
        return self.distance*np.array([math.cos(pitch)*math.cos(yaw),math.cos(pitch)*math.sin(yaw),math.sin(pitch)])

    def initializeGL(self):
        try:
            self._initialize_scene()
            self.ready = True
            self.initialized.emit()
        except Exception as error:
            import traceback
            traceback.print_exc()
            self.render_error = str(error)
            self.ready = False
            self.render_failed.emit(self.render_error)

    def _initialize_scene(self):
        self.viewer = osgViewer.Viewer()
        self.viewer.threadingModel = osgViewer.Viewer.SingleThreaded
        self.graphics = self.viewer.setUpViewerAsEmbeddedInWindow(0, 0, self.width(), self.height())
        self.graphics.state.setUseModelViewAndProjectionUniforms(True)
        self.graphics.state.setUseVertexAttributeAliasing(True)
        self.viewer.camera.clearColor = osg.Vec4(.003, .006, .014, 1)
        self.viewer.camera.computeNearFarMode = osg.Camera.DO_NOT_COMPUTE_NEAR_FAR
        self.root = osg.Group()
        self.earth = geometry(sphere(1,80,160), osg.PrimitiveSet.TRIANGLES, (0,0,0), GLOBE)
        texture_path = Path(__file__).resolve().parent.parent/"assets"/"earth_day.png"
        earth_image = osgDB.readImageFile(str(texture_path))
        if earth_image is None:
            raise RuntimeError(f"无法读取地球纹理：{texture_path}")
        self.earth_texture = osg.Texture2D()
        self.earth_texture.image = earth_image
        self.earth_texture.wrap = (osg.Texture.REPEAT,osg.Texture.CLAMP_TO_EDGE,osg.Texture.CLAMP_TO_EDGE)
        self.earth_texture.filter = (osg.Texture.LINEAR_MIPMAP_LINEAR,osg.Texture.LINEAR)
        self.earth.stateSet.textureAttributes[0] = self.earth_texture
        self.earth.stateSet.uniforms["earthMap"] = 0
        self.earth.stateSet.uniforms["sunDirection"] = osg.Vec3(1,0,0)
        self.earth.stateSet.uniforms["earthAngle"] = 0.0
        self.earth.stateSet.uniforms["showGraticule"] = 1.0 if self.show_graticule else 0.0
        self.earth.stateSet.uniforms["gridSpacing"] = float(self.grid_settings.spacing)
        self.earth.stateSet.uniforms["gridWidth"] = self.grid_settings.width*self.devicePixelRatioF()
        self.earth.stateSet.uniforms["gridColor"] = osg.Vec3(*self.grid_settings.color)
        self.earth.stateSet.uniforms["emphasizeEquator"] = float(self.grid_settings.equator)
        self.earth.stateSet.uniforms["eyePosition"] = osg.Vec3(0,-8,4)
        self.root.children.append(self.earth)
        # Fixed-seed decorative starfield, not a measured astronomical catalogue.
        random = np.random.default_rng(20261115)
        stars = random.normal(size=(4200,3))
        stars = stars/np.linalg.norm(stars,axis=1)[:,None]*100
        self.sky = osg.MatrixTransform()
        stars_node = geometry(stars,osg.PrimitiveSet.POINTS,(1,1,1),STAR_FRAGMENT,STAR_VERTEX)
        stars_node.stateSet.modes[GL_DEPTH_TEST] = osg.StateAttribute.OFF
        stars_node.stateSet.modes[GL_PROGRAM_POINT_SIZE] = osg.StateAttribute.ON
        stars_node.stateSet.setRenderBinDetails(-100,"RenderBin")
        self.sky.children.append(stars_node)
        self.root.children.append(self.sky)
        self.orbits = osg.Group()
        self.root.children.append(self.orbits)
        self.satellite = osg.MatrixTransform()
        self.satellite_node = geometry(sphere(.035, 12, 20), osg.PrimitiveSet.TRIANGLES, (1,.64,.25))
        self.satellite.children.append(self.satellite_node)
        self.root.children.append(self.satellite)
        self.trail = geometry(np.zeros((48,3)),osg.PrimitiveSet.LINE_STRIP,(1,.59,.24))
        self.velocity = geometry(np.zeros((2,3)),osg.PrimitiveSet.LINES,(1,.75,.36))
        for node in (self.trail,self.velocity):
            node.drawables[0].dataVariance = osg.Object.DataVariance.DYNAMIC
            node.drawables[0].vertexArray.dataVariance = osg.Object.DataVariance.DYNAMIC
            self.root.children.append(node)
        self.grid = osg.Group()
        self.root.children.append(self.grid)
        self.shadows = osg.Group()
        self.root.children.append(self.shadows)
        self.umbra = geometry(np.zeros((592,3)),osg.PrimitiveSet.LINES,(.27,.23,.44))
        self.penumbra = geometry(np.zeros((592,3)),osg.PrimitiveSet.LINES,(.10,.19,.28))
        self.sun_arrow = geometry(np.zeros((6,3)),osg.PrimitiveSet.LINES,(.95,.75,.32))
        for node in (self.umbra,self.penumbra,self.sun_arrow):
            node.drawables[0].dataVariance = osg.Object.DataVariance.DYNAMIC
            node.drawables[0].vertexArray.dataVariance = osg.Object.DataVariance.DYNAMIC
            self.shadows.children.append(node)
        self.viewer.sceneData = self.root
        self._build_orbit()
        self._build_batches()
        line_program(self.trail)
        self.apply_line_style()
        self.context().aboutToBeDestroyed.connect(self.cleanup)

    def set_orbit(self, elements):
        self.elements = elements
        self.seconds = 0.0
        self._orbit_bucket = None
        self.home()
        if self.root is not None:
            self._build_orbit()
        self.update()

    def _build_orbit(self):
        if self.elements is None or self.render_error is not None:
            return
        self.orbits.children.clear()
        self.orbit_node = geometry(self.elements.path()/EARTH_RADIUS, osg.PrimitiveSet.LINE_STRIP, (.21,.81,.87))
        self.orbit_node.drawables[0].dataVariance = osg.Object.DataVariance.DYNAMIC
        self.orbit_node.drawables[0].vertexArray.dataVariance = osg.Object.DataVariance.DYNAMIC
        self.orbits.children.append(self.orbit_node)
        line_program(self.orbit_node)
        if hasattr(self,'selected'):
            self.apply_line_style()
        # Mark the apsides with small spheres in the scene itself.
        apsides = [] if is_sgp4(self.elements) else [(0,(.40,.92,.80)), (math.pi,(.57,.63,.96))]
        for nu, color in apsides:
            r = self.elements.a*(1-self.elements.e**2)/(1+self.elements.e*math.cos(nu))
            pos = self.elements.rotation @ np.array([r*math.cos(nu), r*math.sin(nu), 0])/EARTH_RADIUS
            marker = osg.MatrixTransform()
            marker.matrix = osg.Matrixd.translate(osg.Vec3d(*pos))
            marker.children.append(geometry(sphere(.018,8,12),osg.PrimitiveSet.TRIANGLES,color))
            self.orbits.children.append(marker)
        extent = max(2.0, self.elements.a*(1+self.elements.e)/EARTH_RADIUS*1.15)
        lines = []
        for x in np.linspace(-extent, extent, 17):
            lines.extend(((x,-extent,0),(x,extent,0),(-extent,x,0),(extent,x,0)))
        self.grid.children.clear()
        self.grid.children.append(geometry(lines,osg.PrimitiveSet.LINES,(.075,.12,.17)))
        self.grid.nodeMask = 0xffffffff if self.show_grid else 0
        self.set_time(self.seconds)

    def set_time(self, seconds):
        self.seconds = seconds
        if self.root is None or self.elements is None or self.render_error is not None:
            return
        utc = self.elements.utc(seconds)
        sun = solar_position(utc)
        direction = sun/np.linalg.norm(sun)
        self.earth.stateSet.uniforms["sunDirection"].value = osg.Vec3(*direction)
        self.earth.stateSet.uniforms["earthAngle"].value = float(earth_rotation(utc))
        self.sky.nodeMask = 0xffffffff if self.show_stars else 0
        # Sun direction has its own control; the shadow cone remains independent.
        self.shadows.nodeMask = 0xffffffff
        self.umbra.nodeMask = self.penumbra.nodeMask = 0xffffffff if self.show_shadow else 0
        self.sun_arrow.nodeMask = 0xffffffff if self.show_sun else 0
        shadow_bucket = int(utc.timestamp()//60)
        if shadow_bucket!=self._shadow_bucket:
            self._update_vertices(self.umbra,shadow_outline(sun))
            self._update_vertices(self.penumbra,shadow_outline(sun,penumbra=True))
            self._shadow_bucket = shadow_bucket
        side = np.cross(direction,[0,0,1])
        side /= np.linalg.norm(side)
        tip = direction*3.3
        self._update_vertices(self.sun_arrow,[direction*1.2,tip,tip,tip-direction*.18+side*.09,tip,tip-direction*.18-side*.09])
        self.update_stations(earth_rotation(utc))
        if getattr(self,'selected',None) is None:
            self.apply_visibility()
            self.update()
            return
        pos,vel = self.elements.state(seconds)
        self.eclipse_state,self.sun_fraction = eclipse(pos,sun)
        color = np.array([1,.64,.25])*(.23+.77*self.sun_fraction)
        self.satellite_node.stateSet.uniforms["tint"].value = osg.Vec3(*color)
        # SGP4 trajectory advances in absolute time; never wrap it into a fixed ellipse.
        bucket = math.floor(seconds/60)
        if is_sgp4(self.elements) and bucket != self._orbit_bucket:
            self._update_vertices(self.orbit_node,self.elements.path(start_seconds=seconds)/EARTH_RADIUS)
            self._orbit_bucket = bucket
        pos = pos/EARTH_RADIUS
        self.satellite.matrix = osg.Matrixd.translate(osg.Vec3d(*pos))
        # Reuse GPU buffers and programs; only the short trail's vertices change.
        times = np.linspace(seconds-self.elements.period*.10, seconds, 48)
        trail = [self.elements.state(t)[0]/EARTH_RADIUS for t in times]
        self._update_vertices(self.trail,trail)
        self.velocity.nodeMask = 0xffffffff if self.show_velocity else 0
        if self.show_velocity:
            tip = pos+vel/np.linalg.norm(vel)*.48
            self._update_vertices(self.velocity,[pos,tip])
        self.apply_visibility()
        self.update()

    def set_resources(self,crafts,active_id,seconds=0):
        self.resources,self.active_id = crafts,active_id
        self.selected_index = next((i for i,c in enumerate(crafts) if c.uid==active_id),None)
        self.selected = crafts[self.selected_index] if self.selected_index is not None else None
        self.colors = np.asarray([c.color for c in crafts],dtype=np.float32)
        if self.selected is None:
            self.clear_batches()
            if self.root is not None: self.apply_visibility()
            self.update()
            return
        self.set_orbit(self.selected.model)
        if self.root is not None:
            self._build_batches()
        self.set_time(seconds)

    def _build_batches(self):
        if not self.batch_nodes:
            for key,mode,size in [('body',osg.PrimitiveSet.POINTS,3.),('orbit',osg.PrimitiveSet.LINES,1.),
                                  ('trail',osg.PrimitiveSet.LINES,1.),('stations',osg.PrimitiveSet.POINTS,8.)]:
                node = geometry(np.empty((0,3)),mode,(1,1,1),BATCH_FRAGMENT,BATCH_VERTEX)
                node.drawables[0].dataVariance = osg.Object.DataVariance.DYNAMIC
                node.drawables[0].vertexAttrib[1] = osg.Vec3Array(np.empty((0,3),np.float32))
                node.stateSet.uniforms['pointSize'] = size*self.devicePixelRatioF()
                node.stateSet.modes[GL_PROGRAM_POINT_SIZE] = osg.StateAttribute.ON
                self.root.children.append(node)
                self.batch_nodes[key] = node
        self.clear_batches()

    def clear_batches(self):
        for key,node in self.batch_nodes.items():
            if key!='stations': node.drawables[0].primitiveSets[0].count = 0

    def upload(self,key,points,colors):
        if key not in self.batch_nodes:
            return
        geom = self.batch_nodes[key].drawables[0]
        array = osg.Vec3Array(np.ascontiguousarray(points,dtype=np.float32).reshape(-1,3))
        geom.vertexArray = array
        geom.vertexAttrib[0] = array
        color_array = osg.Vec3Array(np.ascontiguousarray(colors,dtype=np.float32).reshape(-1,3))
        color_array.binding = osg.Array.BIND_PER_VERTEX
        geom.vertexAttrib[1] = color_array
        geom.primitiveSets[0].count = len(points)
        geom.dirtyBound()

    def apply_frame(self,frame,visibility):
        mask = visibility[:,0]&frame.valid
        mask[self.selected_index] = False
        positions = frame.positions[mask]/EARTH_RADIUS
        colors = self.colors[mask].copy()
        sun = solar_position(self.elements.utc(frame.seconds))
        axis = sun/np.linalg.norm(sun)
        along = positions@axis
        hidden = (along<0)&((positions*positions).sum(axis=1)-along*along<1)
        colors[hidden] *= .38
        self.upload('body',positions,colors)
        self.update()

    def apply_geometry(self,result):
        for key in ('orbit','trail'):
            points,colors = result[key]
            widths = result.get('line_widths',{}).get(key,np.ones(len(points)))
            ordinary = widths==1
            self.upload(key,points[ordinary],colors[ordinary])
            styled_key = key+'_styled'
            if (~ordinary).any() and styled_key not in self.batch_nodes:
                node = geometry(np.empty((0,3)),osg.PrimitiveSet.LINES,(1,1,1))
                line_program(node)
                self.root.children.append(node)
                self.batch_nodes[styled_key] = node
            if styled_key in self.batch_nodes:
                self.upload(styled_key,points[~ordinary],colors[~ordinary])
                self.line_attributes(self.batch_nodes[styled_key],widths[~ordinary])
        self.update()

    def line_attributes(self,node,widths,color=None):
        geom = node.drawables[0]
        array = osg.Vec3Array(np.repeat(np.asarray(widths,dtype=np.float32)[:,None],3,axis=1))
        array.binding = osg.Array.BIND_PER_VERTEX
        geom.vertexAttrib[2] = array
        if color is not None:
            colors = osg.Vec3Array(np.tile(np.asarray(color,np.float32),(len(widths),1)))
            colors.binding = osg.Array.BIND_PER_VERTEX
            geom.vertexAttrib[1] = colors

    def apply_line_style(self):
        if getattr(self,'orbit_node',None) is None or getattr(self,'selected',None) is None: return
        c = self.selected
        self.line_attributes(self.orbit_node,np.full(721,c.line_width),c.line_color or (.21,.81,.87))
        self.line_attributes(self.trail,np.full(48,c.line_width),c.line_color or (1,.59,.24))
        self.update()

    def update_stations(self,angle):
        visible = [s for s in self.stations if s.visible]
        points = np.array([s.position(angle)/EARTH_RADIUS*1.002 for s in visible]).reshape(-1,3)
        self.upload('stations',points,np.tile([.98,.83,.40],(len(points),1)))

    def apply_visibility(self):
        if getattr(self,'selected',None) is None:
            for node in (self.satellite,self.orbits,self.trail,self.velocity): node.nodeMask = 0
            return
        c = self.selected
        for node,visible in ((self.satellite,c.body),(self.orbits,c.orbit),(self.trail,c.trail),(self.velocity,c.body and self.show_velocity)):
            node.nodeMask = 0xffffffff if visible else 0

    def set_grid_settings(self,settings):
        self.grid_settings = settings
        self.set_graticule(settings.visible)
        if self.ready:
            for key,value in {"gridSpacing":float(settings.spacing),"gridWidth":settings.width*self.devicePixelRatioF(),
                              "gridColor":osg.Vec3(*settings.color),"emphasizeEquator":float(settings.equator)}.items():
                self.earth.stateSet.uniforms[key].value = value
        self.update()

    @staticmethod
    def _update_vertices(node, points):
        geom = node.drawables[0]
        array = osg.Vec3Array(np.ascontiguousarray(points,dtype=np.float32))
        geom.vertexArray = array
        geom.vertexAttrib[0] = array
        geom.dirtyBound()

    def set_graticule(self,visible):
        self.show_graticule = visible
        if self.ready:
            self.earth.stateSet.uniforms["showGraticule"].value = 1.0 if visible else 0.0
        self.update()

    def home(self):
        self.yaw, self.pitch = -65.0, 36.0
        if self.elements:
            sun = solar_position(self.elements.utc(self.seconds))
            sun /= np.linalg.norm(sun)
            pos,vel = self.elements.state(self.seconds)
            normal = np.cross(pos,vel)
            normal /= np.linalg.norm(normal)
            side = normal-np.dot(normal,sun)*sun
            if np.linalg.norm(side) < .01:
                side = np.cross(sun,[0,0,1])
            side /= np.linalg.norm(side)
            eye = .6*sun+.8*side
            self.yaw = math.degrees(math.atan2(eye[1],eye[0]))
            self.pitch = math.degrees(math.asin(eye[2]))
        extent = self.elements.a*(1+self.elements.e)/EARTH_RADIUS if self.elements else 2.5
        self.distance = max(4.5, extent*3.2)
        self.update()

    def top(self):
        self.pitch = 89.0
        self.update()

    def resizeGL(self, width, height):
        if self.viewer and self.ready:
            ratio = self.devicePixelRatioF()
            w, h = max(1,round(width*ratio)), max(1,round(height*ratio))
            self.graphics.resized(0,0,w,h)
            self.viewer.camera.viewport = (0,0,w,h)

    def paintGL(self):
        if not self.viewer or not self.ready:
            return
        self.graphics.defaultFboId = self.defaultFramebufferObject()
        self.resizeGL(self.width(), self.height())
        for node in [self.orbit_node,self.trail]+[node for key,node in self.batch_nodes.items() if key.endswith('_styled')]:
            node.stateSet.uniforms['viewportSize'].value = osg.Vec2(self.width()*self.devicePixelRatioF(),self.height()*self.devicePixelRatioF())
            node.stateSet.uniforms['pixelRatio'].value = self.devicePixelRatioF()
        yaw, pitch = math.radians(self.yaw), math.radians(self.pitch)
        eye = osg.Vec3d(self.distance*math.cos(pitch)*math.cos(yaw),
                       self.distance*math.cos(pitch)*math.sin(yaw), self.distance*math.sin(pitch))
        self.sky.matrix = osg.Matrixd.translate(eye)
        self.earth.stateSet.uniforms["eyePosition"].value = osg.Vec3(eye.x,eye.y,eye.z)
        self.viewer.camera.viewMatrix = osg.Matrixd.lookAt(eye, osg.Vec3d(0,0,0), osg.Vec3d(0,0,1))
        self.viewer.camera.projectionMatrix = osg.Matrixd.perspective(38.0,self.width()/max(1,self.height()),.05,max(200.,self.distance*5))
        start = time.perf_counter()
        self.viewer.frame()
        self.frame_count += 1
        self.frame_times.append((time.perf_counter()-start)*1000)
        if len(self.frame_times)>3000: del self.frame_times[:1000]

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._last_mouse = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._last_mouse is not None:
            delta = event.position()-self._last_mouse
            self.yaw -= delta.x()*.35
            self.pitch = max(-89,min(89,self.pitch+delta.y()*.35))
            self._last_mouse = event.position()
            self.update()

    def mouseReleaseEvent(self, event):
        self._last_mouse = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def wheelEvent(self, event):
        self.distance = max(2.2,min(150,self.distance*math.exp(-event.angleDelta().y()/120*.12)))
        self.update()

    def cleanup(self):
        if self.viewer:
            self.makeCurrent()
            self.ready = False
            # Drop GPU-owning references while Qt's context is still current,
            # including views hidden behind the welcome page at shutdown.
            self.viewer.sceneData = None
            self.batch_nodes.clear()
            for name in ('root','earth','earth_texture','sky','orbits','satellite','satellite_node',
                         'trail','velocity','grid','shadows','umbra','penumbra','sun_arrow','orbit_node'):
                setattr(self,name,None)
            self.viewer.close()
            self.viewer = None
            self.graphics = None
            self.doneCurrent()
