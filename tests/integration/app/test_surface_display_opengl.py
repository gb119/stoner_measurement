"""Optional native OpenGL framebuffer proof, separate from offscreen Qt tests."""

import numpy as np
import pytest
from qtpy.QtGui import (
    QOffscreenSurface,
    QOpenGLContext,
    QOpenGLFramebufferObject,
    QOpenGLFramebufferObjectFormat,
)
from qtpy.QtWidgets import QWidget

from stoner_measurement.core.plotting.contracts import (
    CoordinateBinding,
    PlotData,
    Presentation,
    SeriesUpdate,
    SurfaceBinding,
)
from stoner_measurement.ui.plotting.surface_displays import Cartesian3DDisplayFactory


def test_xyz_mesh_paints_into_native_opengl_framebuffer(qapp, managed_qt_widget, capsys):
    if qapp.platformName() in ("offscreen", "minimal"):
        pytest.skip("Run with a native Qt platform to validate OpenGL painting.")
    from OpenGL import GL

    context = QOpenGLContext()
    if not context.create():
        pytest.skip("The native graphics driver cannot create an OpenGL context.")
    surface = QOffscreenSurface()
    surface.setFormat(context.format())
    surface.create()
    if not surface.isValid() or not context.makeCurrent(surface):
        surface.destroy()
        pytest.skip("The native graphics driver cannot create an offscreen surface.")
    parent = managed_qt_widget(QWidget())
    display = Cartesian3DDisplayFactory().create(parent)
    managed_qt_widget(display)
    assert context.makeCurrent(surface)
    framebuffer_format = QOpenGLFramebufferObjectFormat()
    framebuffer_format.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
    framebuffer = QOpenGLFramebufferObject(400, 400, framebuffer_format)
    try:
        display.canvas.view.resize(400, 400)
        display.apply(
            SeriesUpdate(
                "mesh",
                PlotData({"x": [0, 1, 0, 1], "y": [0, 0, 1, 1], "z": [0, 1, 1, 2]}),
                CoordinateBinding("x", "y", "z"),
                presentation=Presentation.SURFACE,
                surface=SurfaceBinding("mesh", duplicates="replace"),
            )
        )
        display.refresh()
        mesh = display.canvas._geometry[("mesh", "mesh")]
        display.apply(
            SeriesUpdate(
                "mesh",
                PlotData({"x": [0, 1, 0, 1], "y": [0, 0, 1, 1], "z": [0, 2, 2, 3]}),
                CoordinateBinding("x", "y", "z"),
                presentation=Presentation.SURFACE,
                surface=SurfaceBinding("mesh", duplicates="replace"),
            )
        )
        display.refresh()
        assert display.canvas._geometry[("mesh", "mesh")] is mesh
        # GLTextItem paints through QPainter on its widget, outside this hidden
        # framebuffer path. This test proves GPU mesh/point/axis-line painting.
        for item in display.canvas.view.items:
            if isinstance(item, display.canvas.gl.GLTextItem):
                item.setVisible(False)
            item.initialize()
        assert framebuffer.isValid() and framebuffer.bind()
        GL.glViewport(0, 0, 400, 400)
        display.canvas.view.paintGL()
        GL.glFinish()
        pixels = np.frombuffer(
            GL.glReadPixels(0, 0, 400, 400, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE), dtype=np.uint8
        ).reshape(400, 400, 4)
        assert np.count_nonzero(np.any(pixels[:, :, :3] > 30, axis=2)) > 1000
        assert GL.glGetError() == GL.GL_NO_ERROR
        assert "Error while drawing" not in capsys.readouterr().out
    finally:
        display.close()
        framebuffer.release()
        del framebuffer
        context.doneCurrent()
        surface.destroy()
