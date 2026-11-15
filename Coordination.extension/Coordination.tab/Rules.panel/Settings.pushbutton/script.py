# -*- coding: utf-8 -*-
"""Open the coordination rules (settings.json) for editing.
Shift+Click: reset your rules to the extension defaults."""
__title__ = "Rules\nSettings"
__author__ = "Coordination"

import os
import shutil

from pyrevit import forms

from coordination import config

if __shiftclick__:  # noqa: F821  (injected by pyRevit)
    if forms.alert("Reset your rules to the defaults?\n\n{}".format(config.USER_PATH),
                   yes=True, no=True):
        config.ensure_user_file()
        shutil.copyfile(config.DEFAULTS_PATH, config.USER_PATH)
        forms.alert("Rules reset to defaults.")
else:
    path = config.ensure_user_file()
    os.startfile(path)
