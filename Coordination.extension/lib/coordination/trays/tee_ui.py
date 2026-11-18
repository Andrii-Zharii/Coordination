# -*- coding: utf-8 -*-
"""Window with one card per tier scheme of a junction: words, a section sketch,
a temporary 3D picture on demand, and an apply button."""
import clr
import tempfile
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
from System import Uri, UriKind
from System.Windows import (Window, Thickness, HorizontalAlignment, VerticalAlignment, TextWrapping,
                            FontWeights, MessageBox, MessageBoxButton, MessageBoxResult, Visibility,
                            WindowStartupLocation)
from System.Windows.Controls import (Border, Button, Canvas, Image, Orientation, ScrollViewer,
                                     ScrollBarVisibility, StackPanel, TextBlock)
from System.Windows.Input import Cursors, Mouse
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Media import Brushes, Color, DoubleCollection, SolidColorBrush
from System.Windows.Media.Imaging import BitmapCacheOption, BitmapImage
from System.Windows.Shapes import Line, Rectangle
from coordination.trays import tees as T

MM = T.MM
TOP_CARDS = 4
TRAY_COLORS = [Color.FromRgb(37, 99, 200), Color.FromRgb(220, 110, 30), Color.FromRgb(30, 150, 90)]
STATUS = {"ok": u"✔ Без колізій, перевірено", "soft": u"⚠ М'які колізії, перевірено",
          "est": u"◌ Ще не збудовано, попередня оцінка", "hard": u"✖ Не проходить",
          "fail": u"✖ Не проходить", "skip": u"– Не проходить"}


def _short(m):
    return m["name"].split()[0]


def _join(names):
    return u" і ".join(names)


def summary(ms, pl):
    """Plain-language lines describing what a plan does to each tray."""
    lines = []
    dzs = [p["dz"] if p else 0.0 for p in pl]
    for m, p in zip(ms, pl):
        size = int(round(m["W"] / MM))
        base = int(round(m["offset"] / MM))
        if p is None:
            lines.append(u"%s %d: без змін, %d" % (_short(m), size, base))
            continue
        dz = int(round(p["dz"] / MM))
        word = u"підйом" if dz > 0 else u"спуск"
        text = u"%s %d: %s %+d, з %d на %d" % (_short(m), size, word, dz, base, base + dz)
        notes = []
        targets = [t for t in p["legs"] if t]
        if targets or p["target"]:
            notes.append(u"старі переходи злито в одну рампу")
        if any(t["narrow"] for t in targets) or any(l["reducer"] for l in m["mains"]):
            notes.append(u"перехідник перебудовано")
        if notes:
            text += u" (" + u", ".join(notes) + u")"
        lines.append(text)
    for k in range(1, len(ms)):
        over = [T.short_name(ms[i], ms) for i in range(k) if dzs[k] > dzs[i]]
        under = [T.short_name(ms[i], ms) for i in range(k) if dzs[k] < dzs[i]]
        parts = []
        if over:
            parts.append(u"над " + _join(over))
        if under:
            parts.append(u"під " + _join(under))
        lines.append(u"Відгалуження %s іде %s" % (T.short_name(ms[k], ms), u", ".join(parts)))
    return lines


def _text(canvas, s, x, y, brush=None, size=10):
    t = TextBlock()
    t.Text = s
    t.FontSize = size
    t.Foreground = brush or Brushes.Black
    Canvas.SetLeft(t, x)
    Canvas.SetTop(t, y)
    canvas.Children.Add(t)
    return t


def _rect(canvas, x, y, w, h, fill=None, stroke=None, dash=False, thick=1.0):
    r = Rectangle()
    r.Width = max(w, 1)
    r.Height = max(h, 1)
    if fill is not None:
        r.Fill = fill
    if stroke is not None:
        r.Stroke = stroke
        r.StrokeThickness = thick
    if dash:
        r.StrokeDashArray = DoubleCollection([3.0, 2.0])
    Canvas.SetLeft(r, x)
    Canvas.SetTop(r, y)
    canvas.Children.Add(r)
    return r


def schematic(ms, pl, obstacles, width=340, height=210):
    """Section through the mains: dashed = height now, filled = height after,
    grey = structure above, green = opening, red = the 2300 limit."""
    c = Canvas()
    c.Width = width
    c.Height = height
    c.Background = Brushes.White
    level_z = ms[0]["PT"].Z - ms[0]["offset"]
    to_mm = lambda z: (z - level_z) / MM
    v = ms[0]["v"]
    pos = [m["PT"].DotProduct(v) for m in ms]
    tops, bottoms = [], []
    for m, p in zip(ms, pl):
        base = m["offset"] / MM
        dz = p["dz"] / MM if p else 0.0
        half = m["H"] / MM / 2
        tops.extend([base + half, base + dz + half])
        bottoms.extend([base - half, base + dz - half])
    near = 3.0
    lo_x = min(m["PT"].X for m in ms) - near
    hi_x = max(m["PT"].X for m in ms) + near
    lo_y = min(m["PT"].Y for m in ms) - near
    hi_y = max(m["PT"].Y for m in ms) + near
    z_lo = min(bottoms) - 120
    z_hi = max(tops) + 150
    z_lo = min(z_lo, T.MIN_OFFSET / MM - 60)
    margin_l, margin_r, margin_t, margin_b = 42, 14, 8, 8
    y_of = lambda mm: margin_t + (z_hi - mm) * (height - margin_t - margin_b) / (z_hi - z_lo)
    plot_w = width - margin_l - margin_r
    for a, b in obstacles.openings if obstacles else []:
        if b.X < lo_x or a.X > hi_x or b.Y < lo_y or a.Y > hi_y:
            continue
        o_lo, o_hi = to_mm(a.Z), to_mm(b.Z)
        if o_hi < z_lo or o_lo > z_hi:
            continue
        top = y_of(min(o_hi, z_hi))
        bot = y_of(max(o_lo, z_lo))
        _rect(c, margin_l, top, plot_w, bot - top, Brushes.Honeydew, Brushes.SeaGreen, True)
        _text(c, u"отвір %d-%d" % (round(o_lo), round(o_hi)), margin_l + 2, top + 1, Brushes.SeaGreen, 9)
        break
    beam = None
    for a, b in obstacles.boxes if obstacles else []:
        if b.X < lo_x or a.X > hi_x or b.Y < lo_y or a.Y > hi_y:
            continue
        low = to_mm(a.Z)
        if max(tops) - 300 < low <= z_hi and (beam is None or low < beam):
            beam = low
    if beam is not None:
        _rect(c, margin_l, margin_t, plot_w, y_of(beam) - margin_t, Brushes.LightGray, Brushes.Gray)
        _text(c, u"бетон, низ %d" % round(beam), margin_l + 2, margin_t + 1, Brushes.DimGray, 9)
    y_lim = y_of(T.MIN_OFFSET / MM)
    limit = Line()
    limit.X1, limit.X2, limit.Y1, limit.Y2 = margin_l, width - margin_r, y_lim, y_lim
    limit.Stroke = Brushes.Red
    limit.StrokeDashArray = DoubleCollection([4.0, 3.0])
    c.Children.Add(limit)
    _text(c, u"2300", 8, y_lim - 7, Brushes.Red, 9)
    lo, hi = min(pos), max(pos)
    span = max(hi - lo, 0.5)
    widest = max(m["W"] for m in ms)
    x_scale = plot_w / (span + widest * 1.6)
    for i, (m, p) in enumerate(zip(ms, pl)):
        cx = margin_l + (pos[i] - lo + widest * 0.8) * x_scale
        w = max(m["W"] * x_scale, 16)
        base = m["offset"] / MM
        half = m["H"] / MM / 2
        brush = SolidColorBrush(TRAY_COLORS[i % 3])
        dz = p["dz"] / MM if p else 0.0
        top = y_of(base + dz + half)
        bottom = y_of(base + dz - half)
        if p:
            old_top = y_of(base + half)
            _rect(c, cx - w / 2, old_top, w, y_of(base - half) - old_top, None, Brushes.DimGray, True)
        _rect(c, cx - w / 2, top, w, bottom - top, brush, Brushes.Black)
        _text(c, T.short_name(m, ms), cx - w / 2 + 2, top + 1, Brushes.White, 9)
        _text(c, u"%d" % round(base + dz), cx - 12, bottom + 1, brush, 9)
    return c


def _load_image(path):
    bmp = BitmapImage()
    bmp.BeginInit()
    bmp.CacheOption = BitmapCacheOption.OnLoad
    bmp.UriSource = Uri(path, UriKind.Absolute)
    bmp.EndInit()
    return bmp


def _clash_text(opt):
    if opt["hard"]:
        return u"Заважає: " + u", ".join(u"%s %s %d" % (r[0], r[2], r[1]) for r in opt["hard"][:4])
    if opt["soft"]:
        return u"Перевірте вручну: " + u", ".join(u"%s %s %d" % (r[0], r[2], r[1]) for r in opt["soft"][:5])
    return u""


class Chooser(object):
    """Modal window; after show(), `chosen` holds the option to apply, or None."""

    def __init__(self, doc, g, title, opts, obstacles, owner=None):
        self.doc, self.g, self.opts, self.obstacles = doc, g, opts, obstacles
        self.chosen = None
        self.folder = tempfile.mkdtemp(prefix="split_tee_")
        self.win = Window()
        self.win.Title = title
        self.win.Width = 860
        self.win.Height = 760
        self.win.WindowStartupLocation = WindowStartupLocation.CenterOwner if owner else WindowStartupLocation.CenterScreen
        if owner:
            WindowInteropHelper(self.win).Owner = owner
        self.panel = StackPanel()
        self.panel.Margin = Thickness(10)
        scroll = ScrollViewer()
        scroll.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        scroll.Content = self.panel
        self.win.Content = scroll
        legend = TextBlock()
        legend.Text = (u"Схема: розріз по магістралях. Пунктир — висота зараз, заливка — після змін, "
                       u"сіре — бетон, зелене — отвір. Числа — Elevation from Level у мм (центр лотка); "
                       u"межа 2300 (червона) стосується цього числа, а не низу лотка.")
        legend.TextWrapping = TextWrapping.Wrap
        legend.Margin = Thickness(0, 0, 0, 8)
        self.panel.Children.Add(legend)
        usable = sorted([o for o in opts if self._clean(o)], key=self._rank)
        forced = sorted([o for o in opts if T.overridable(o)], key=lambda o: (bool(o.get("low")), len(o["hard"]), len(o["soft"])))
        dead = [o for o in opts if not self._clean(o) and not T.overridable(o)]
        top = usable[:TOP_CARDS]
        if not usable:
            none = TextBlock()
            none.Text = u"Жоден варіант не проходить за правилами." + (
                u" Нижче найменш погані: їх можна застосувати всеодно." if forced else u" Причини нижче.")
            none.FontWeight = FontWeights.Bold
            none.TextWrapping = TextWrapping.Wrap
            none.Margin = Thickness(0, 0, 0, 8)
            self.panel.Children.Add(none)
            top = forced[:TOP_CARDS]
            forced = forced[TOP_CARDS:]
        rest = usable[TOP_CARDS:] + forced + dead
        for o in top:
            self.panel.Children.Add(self._card(o))
        if rest:
            more = Button()
            more.Content = u"Показати всі варіанти (ще %d)" % len(rest)
            more.Margin = Thickness(0, 6, 0, 6)
            more.Padding = Thickness(6)

            def on_more(s, e):
                more.Visibility = Visibility.Collapsed
                for o in rest:
                    self.panel.Children.Add(self._card(o))
            more.Click += on_more
            self.panel.Children.Add(more)

    def _clean(self, o):
        return o["status"] in ("ok", "soft", "est") and not o.get("low")

    def _rank(self, o):
        return ({"ok": 0, "soft": 1, "est": 2}[o["status"]], len(o["soft"]))

    def show(self):
        self.win.ShowDialog()
        return self.chosen

    def _card(self, opt):
        ms = T._members(self.doc, self.g)
        pl = None
        if opt["status"] not in ("skip",):
            pl, _ = T.plan(ms, opt["scheme"], self.obstacles, opt.get("low", False))
        border = Border()
        border.BorderBrush = Brushes.Silver
        border.BorderThickness = Thickness(1)
        border.Margin = Thickness(0, 0, 0, 8)
        border.Padding = Thickness(8)
        box = StackPanel()
        border.Child = box
        row = StackPanel()
        row.Orientation = Orientation.Horizontal
        box.Children.Add(row)
        if pl is not None:
            row.Children.Add(schematic(ms, pl, self.obstacles))
        info = StackPanel()
        info.Margin = Thickness(12, 0, 0, 0)
        info.Width = 450
        row.Children.Add(info)
        head = TextBlock()
        head.Text = opt["label"]
        head.FontWeight = FontWeights.Bold
        head.FontSize = 14
        info.Children.Add(head)
        state = TextBlock()
        state.TextWrapping = TextWrapping.Wrap
        state.Margin = Thickness(0, 2, 0, 6)
        info.Children.Add(state)
        if pl is not None:
            for line in summary(ms, pl):
                t = TextBlock()
                t.Text = line
                t.TextWrapping = TextWrapping.Wrap
                info.Children.Add(t)
        clash = TextBlock()
        clash.TextWrapping = TextWrapping.Wrap
        clash.Margin = Thickness(0, 6, 0, 0)
        clash.Foreground = Brushes.Sienna
        info.Children.Add(clash)
        buttons = StackPanel()
        buttons.Orientation = Orientation.Horizontal
        buttons.Margin = Thickness(0, 8, 0, 0)
        info.Children.Add(buttons)
        picture = Image()
        picture.Visibility = Visibility.Collapsed
        picture.Margin = Thickness(0, 8, 0, 0)
        picture.MaxHeight = 520
        box.Children.Add(picture)
        apply_btn = Button()

        def refresh():
            word = STATUS[opt["status"]]
            if opt.get("why"):
                word += u": " + opt["why"]
            if opt.get("low"):
                word += u"; " + T.BELOW_LIMIT
            state.Text = word
            clash.Text = _clash_text(opt)
            forced = T.overridable(opt)
            shown = self._clean(opt) or forced
            buttons.Visibility = Visibility.Visible if shown else Visibility.Collapsed
            apply_btn.Content = u"Застосувати всеодно" if forced else u"Застосувати"
            apply_btn.Foreground = Brushes.DarkRed if forced else Brushes.Black

        def busy(on):
            Mouse.OverrideCursor = Cursors.Wait if on else None

        def on_view(s, e):
            busy(True)
            try:
                if opt["status"] == "est":
                    T.verify(self.doc, self.g, opt, self.obstacles)
                    refresh()
                path, errors = T.preview_image(self.doc, self.g, opt["scheme"], self.obstacles, self.folder,
                                               opt.get("low", False))
            finally:
                busy(False)
            if path:
                picture.Source = _load_image(path)
                picture.Visibility = Visibility.Visible
            else:
                MessageBox.Show(self.win, u"Не вдалося зробити 3D-знімок, модель не змінено.\n" +
                                u"\n".join(errors), u"Split Tee")

        def ask(text):
            return MessageBox.Show(self.win, text, u"Split Tee", MessageBoxButton.YesNo) == MessageBoxResult.Yes

        def on_apply(s, e):
            tested = opt["status"] in ("ok", "soft") or opt.get("tested")
            if not tested:
                busy(True)
                try:
                    T.verify(self.doc, self.g, opt, self.obstacles)
                finally:
                    busy(False)
                opt["tested"] = True
                refresh()
                if opt["status"] in ("fail", "skip") or opt.get("inner"):
                    MessageBox.Show(self.win, u"Цей варіант неможливо застосувати: %s.\nВиберіть інший." % (
                        opt.get("why") or u"не пройшов перевірку"), u"Split Tee")
                    return
            if T.overridable(opt):
                broken = []
                if opt.get("low"):
                    broken.append(u"Нижче 2300 мм від рівня.")
                if opt["hard"]:
                    broken.append(_clash_text(opt))
                if not ask(u"Цей варіант порушує правила:\n\n%s\n\nЗастосувати всеодно?" % u"\n".join(broken)):
                    return
            elif opt["status"] == "soft" and not ask(_clash_text(opt) + u"\n\nЗастосувати?"):
                return
            self.chosen = opt
            self.win.Close()

        view_btn = Button()
        view_btn.Content = u"Показати в 3D"
        view_btn.Padding = Thickness(10, 4, 10, 4)
        view_btn.Click += on_view
        buttons.Children.Add(view_btn)
        apply_btn.Padding = Thickness(10, 4, 10, 4)
        apply_btn.Margin = Thickness(8, 0, 0, 0)
        apply_btn.FontWeight = FontWeights.Bold
        apply_btn.Click += on_apply
        buttons.Children.Add(apply_btn)
        refresh()
        return border
