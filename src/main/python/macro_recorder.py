# SPDX-License-Identifier: GPL-2.0-or-later

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QPushButton, QGridLayout, QHBoxLayout, QToolButton, QVBoxLayout, \
    QTabWidget, QWidget, QLabel, QMenu

from basic_editor import BasicEditor
from keycodes import find_keycode
from macro_action import ActionText, ActionTap, ActionDown, ActionUp
from macro_key import KeyString, KeyDown, KeyUp, KeyTap
from macro_line import MacroLine
from macro_optimizer import macro_optimize
from macro_recorder_linux import LinuxRecorder
from util import tr
from vial_device import VialKeyboard


class MacroTab(QVBoxLayout):

    changed = pyqtSignal()
    record = pyqtSignal(object, bool)
    record_stop = pyqtSignal()

    def __init__(self):
        super().__init__()

        self.lines = []

        self.container = QGridLayout()

        menu_record = QMenu()
        menu_record.addAction(tr("MacroRecorder", "Append to current"))\
            .triggered.connect(lambda: self.record.emit(self, True))
        menu_record.addAction(tr("MacroRecorder", "Replace everything"))\
            .triggered.connect(lambda: self.record.emit(self, False))

        self.btn_record = QPushButton(tr("MacroRecorder", "Record macro"))
        self.btn_record.setMenu(menu_record)

        self.btn_record_stop = QPushButton(tr("MacroRecorder", "Stop recording"))
        self.btn_record_stop.clicked.connect(lambda: self.record_stop.emit())
        self.btn_record_stop.hide()

        self.btn_add = QToolButton()
        self.btn_add.setText(tr("MacroRecorder", "Add action"))
        self.btn_add.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.btn_add.clicked.connect(self.on_add)

        self.btn_tap_enter = QToolButton()
        self.btn_tap_enter.setText(tr("MacroRecorder", "Tap Enter"))
        self.btn_tap_enter.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.btn_tap_enter.clicked.connect(self.on_tap_enter)

        layout_buttons = QHBoxLayout()
        layout_buttons.addStretch()
        layout_buttons.addWidget(self.btn_add)
        layout_buttons.addWidget(self.btn_tap_enter)
        layout_buttons.addWidget(self.btn_record)
        layout_buttons.addWidget(self.btn_record_stop)

        self.addLayout(self.container)
        self.addLayout(layout_buttons)
        self.addStretch()

    def add_action(self, act):
        line = MacroLine(self, act)
        line.changed.connect(self.on_change)
        self.lines.append(line)
        line.insert(self.container.rowCount())
        self.changed.emit()

    def on_add(self):
        self.add_action(ActionText(self.container))

    def on_remove(self, obj):
        for line in self.lines:
            if line == obj:
                line.remove()
                line.delete()
        self.lines.remove(obj)
        for line in self.lines:
            line.remove()
        for x, line in enumerate(self.lines):
            line.insert(x)
        self.changed.emit()

    def clear(self):
        for line in self.lines[:]:
            self.on_remove(line)

    def on_move(self, obj, offset):
        if offset == 0:
            return
        index = self.lines.index(obj)
        if index + offset < 0 or index + offset >= len(self.lines):
            return
        other = self.lines.index(self.lines[index + offset])
        self.lines[index].remove()
        self.lines[other].remove()
        self.lines[index], self.lines[other] = self.lines[other], self.lines[index]
        self.lines[index].insert(index)
        self.lines[other].insert(other)
        self.changed.emit()

    def serialize(self):
        out = b""
        for line in self.lines:
            out += line.serialize()
        return out

    def on_change(self):
        self.changed.emit()

    def on_tap_enter(self):
        self.add_action(ActionTap(self.container, [find_keycode(0x28)]))

    def pre_record(self):
        self.btn_record.hide()
        self.btn_add.hide()
        self.btn_tap_enter.hide()
        self.btn_record_stop.show()

    def post_record(self):
        self.btn_record.show()
        self.btn_add.show()
        self.btn_tap_enter.show()
        self.btn_record_stop.hide()


class MacroRecorder(BasicEditor):

    def __init__(self):
        super().__init__()

        self.keystrokes = []
        self.macro_tabs = []

        self.recorder = LinuxRecorder()
        self.recorder.keystroke.connect(self.on_keystroke)
        self.recorder.stopped.connect(self.on_stop)
        self.recording = False

        self.recording_tab = None
        self.recording_append = False

        self.tabs = QTabWidget()
        for x in range(32):
            tab = MacroTab()
            tab.changed.connect(self.on_change)
            tab.record.connect(self.on_record)
            tab.record_stop.connect(self.on_tab_stop)
            self.macro_tabs.append(tab)
            w = QWidget()
            w.setLayout(tab)
            self.tabs.addTab(w, "Macro {}".format(x + 1))

        self.lbl_memory = QLabel()

        buttons = QHBoxLayout()
        buttons.addWidget(self.lbl_memory)
        buttons.addStretch()
        buttons.addWidget(QPushButton("Save"))
        buttons.addWidget(QPushButton("Revert"))

        self.addWidget(self.tabs)
        self.addLayout(buttons)

        self.on_change()

    def valid(self):
        return isinstance(self.device, VialKeyboard)

    def rebuild(self, device):
        super().rebuild(device)
        if not self.valid():
            return

    def on_record(self, tab, append):
        self.recording_tab = tab
        self.recording_append = append

        self.recording_tab.pre_record()

        for x, w in enumerate(self.macro_tabs):
            if tab != w:
                self.tabs.tabBar().setTabEnabled(x, False)

        self.recording = True
        self.keystrokes = []
        self.recorder.start()

    def on_tab_stop(self):
        self.recorder.stop()

    def on_stop(self):
        for x in range(len(self.macro_tabs)):
            self.tabs.tabBar().setTabEnabled(x, True)

        if not self.recording_append:
            self.recording_tab.clear()

        self.recording_tab.post_record()

        self.keystrokes = macro_optimize(self.keystrokes)
        for k in self.keystrokes:
            if isinstance(k, KeyString):
                self.recording_tab.add_action(ActionText(self.recording_tab.container, k.string))
            else:
                cls = {KeyDown: ActionDown, KeyUp: ActionUp, KeyTap: ActionTap}[type(k)]
                self.recording_tab.add_action(cls(self.recording_tab.container, [k.keycode]))

    def on_keystroke(self, keystroke):
        self.keystrokes.append(keystroke)

    def on_change(self):
        memory = 0
        for x, macro in enumerate(self.macro_tabs):
            memory += len(macro.serialize())
        self.lbl_memory.setText("Memory used by macros: {}/345".format(memory))