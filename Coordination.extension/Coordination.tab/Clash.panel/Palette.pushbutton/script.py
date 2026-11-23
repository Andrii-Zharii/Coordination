# -*- coding: utf-8 -*-
"""Floating palette: previous / next clash group, refresh the group, zone note."""
__persistentengine__ = True

from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent
from pyrevit import forms

from coordination import session
from coordination.clash import core as gc

XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Coordination" Topmost="True" WindowStyle="ToolWindow" ResizeMode="NoResize"
        SizeToContent="WidthAndHeight" ShowInTaskbar="False" WindowStartupLocation="Manual" Left="200" Top="200">
  <StackPanel Margin="6">
    <StackPanel Orientation="Horizontal">
      <Button x:Name="prev_button" Content="&#x25C0; Попередня" Padding="8,4" Margin="2" Click="on_prev"/>
      <Button x:Name="next_button" Content="Наступна &#x25B6;" Padding="8,4" Margin="2" Click="on_next"/>
      <Button x:Name="refresh_button" Content="&#x21BB; Оновити групу" Padding="8,4" Margin="2" Click="on_refresh"/>
    </StackPanel>
    <TextBlock x:Name="status" Margin="2,4" MaxWidth="420" TextWrapping="Wrap" Text="Готово"/>
    <StackPanel Orientation="Horizontal">
      <TextBox x:Name="note_box" Width="300" Margin="2" Padding="2" ToolTip="Zone Note: що зробили і чому"/>
      <Button x:Name="note_button" Content="Zone Note" Padding="8,4" Margin="2" Click="on_note"/>
    </StackPanel>
  </StackPanel>
</Window>
"""


class Handler(IExternalEventHandler):
    """Runs the requested action inside Revit's API context."""

    def __init__(self):
        self.action = None
        self.window = None

    def Execute(self, uiapp):
        action, self.action = self.action, None
        if action is None or self.window is None:
            return
        try:
            self.window.set_status(action(uiapp.ActiveUIDocument))
        except Exception as error:
            self.window.set_status(u"Помилка: {}".format(error))

    def GetName(self):
        return u"Coordination palette"


def do_step(step):
    def run(uidoc):
        header, text = gc.navigate(uidoc, step=step)
        return u"{}\n{}".format(header, text)
    return run


def do_refresh(uidoc):
    name, before, after, other = gc.refresh_group(uidoc)
    if after:
        gc.navigate(uidoc, index=gc.load_results()["current"])
        text = u"{}: було {}, лишилось {}.".format(name, before, after)
    else:
        text = u"{}: вирішено (було {}). Бокси прибрано.".format(name, before)
    if other:
        text += u" Поруч інших колізій: {}.".format(other)
    return text


def do_note(text):
    def run(uidoc):
        doc = uidoc.Document
        state = session.pending_session(doc)
        if state is None:
            return u"Немає відкритої зони: спершу Start Zone."
        selection = [gc.id_int(i) for i in uidoc.Selection.GetElementIds()]
        number, image_ok = session.add_note(doc, uidoc.ActiveView, state, text, selection)
        return u"Нотатку {} збережено{}.".format(number, u"" if image_ok else u" (без скриншота)")
    return run


class Palette(forms.WPFWindow):
    def __init__(self):
        forms.WPFWindow.__init__(self, XAML, literal_string=True)
        self.handler = Handler()
        self.handler.window = self
        self.event = ExternalEvent.Create(self.handler)

    def set_status(self, text):
        self.status.Text = text

    def request(self, action, busy):
        self.handler.action = action
        self.set_status(busy)
        self.event.Raise()

    def on_prev(self, sender, args):
        self.request(do_step(-1), u"...")

    def on_next(self, sender, args):
        self.request(do_step(1), u"...")

    def on_refresh(self, sender, args):
        self.request(do_refresh, u"Перевіряю групу...")

    def on_note(self, sender, args):
        text = (self.note_box.Text or u"").strip()
        if not text:
            self.set_status(u"Напишіть нотатку в полі ліворуч.")
            return
        self.note_box.Text = u""
        self.request(do_note(text), u"Зберігаю нотатку...")


Palette().show()
