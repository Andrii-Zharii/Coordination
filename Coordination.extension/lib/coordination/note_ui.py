# -*- coding: utf-8 -*-
"""Asking the user for a case note: voice (any language) or text."""
import os
import tempfile

from pyrevit import forms

from coordination import voice

VOICE = u"Record voice"
TEXT = u"Type text"
NONE = u"No note"


def ask_note(title, question):
    """Returns (text, wav_path) - wav_path is a temporary file or None.
    Returns None when the user cancelled."""
    choice = forms.alert(question, title=title, options=[VOICE, TEXT, NONE])
    if choice is None:
        return None
    if choice == NONE:
        return u"", None
    if choice == TEXT:
        text = forms.ask_for_string(prompt=question, title=title)
        if text is None:
            return None
        return text, None

    path = os.path.join(tempfile.gettempdir(), u"coordination_note_pending.wav")
    try:
        voice.start()
    except Exception as error:
        forms.alert(u"Could not start the microphone:\n{}".format(error), title=title)
        return None
    answer = forms.alert(u"Recording...  Speak now (any language).",
                         sub_msg=question,
                         title=title, options=[u"Stop and save", u"Cancel"])
    if answer != u"Stop and save":
        voice.cancel()
        return None
    try:
        size = voice.stop(path)
    except Exception as error:
        forms.alert(u"Could not save the recording:\n{}".format(error), title=title)
        return None
    if size < 2000:
        forms.alert(u"The recording is empty. Check the microphone.", title=title)
        return None
    return u"", path
