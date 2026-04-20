"""Central translation dictionary for user-visible strings.

One flat key → {lang_code: translated_string} mapping. German and
English are the two supported languages for now; adding a third is as
simple as extending each entry. Keys are stable — never rename a key
without also updating every call site.

Language is set once at startup from ``Settings.language``. A change
requires an app restart (we don't rebuild widgets on the fly), and the
Settings dialog tells the user so explicitly.

Usage::

    from .i18n import t
    label = t("chat.send_button")

``t`` falls back to English when a key is missing in the active
language, and to the raw key when English is missing too — so a typo
never crashes the UI, it just renders as the key itself (easy to spot
in testing).
"""

from __future__ import annotations

from typing import Literal

Language = Literal["de", "en"]


_current: Language = "en"


LANGUAGE_NAMES: dict[Language, str] = {
    "de": "Deutsch",
    "en": "English",
}


TRANSLATIONS: dict[str, dict[Language, str]] = {
    # --- app-wide / menus ---
    "app.title": {
        "de": "FlameChat {version}",
        "en": "FlameChat {version}",
    },
    "menu.file": {"de": "&Datei", "en": "&File"},
    "menu.file.new_chat": {"de": "&Neuer Chat\tCtrl+N", "en": "&New Chat\tCtrl+N"},
    "menu.file.prefs": {"de": "&Einstellungen …\tCtrl+,", "en": "&Preferences …\tCtrl+,"},
    "menu.file.quit": {"de": "&Beenden\tCtrl+Q", "en": "&Quit\tCtrl+Q"},
    "menu.models": {"de": "&Modelle", "en": "&Models"},
    "menu.models.manage": {
        "de": "&Modelle verwalten …\tCtrl+M",
        "en": "&Manage models …\tCtrl+M",
    },
    "menu.help": {"de": "&Hilfe", "en": "&Help"},
    "menu.help.about": {"de": "Über FlameChat", "en": "About FlameChat"},

    "status.shortcuts": {
        "de": (
            "Cmd+1: Chat-Liste · Cmd+2: Nachricht · Cmd+,: Einstellungen · "
            "Ctrl+Cmd+↑/↓: Nachricht davor/danach · Alt+1…0…ß: letzte 11 Nachrichten vorlesen"
        ),
        "en": (
            "Cmd+1: chat list · Cmd+2: message · Cmd+,: preferences · "
            "Ctrl+Cmd+↑/↓: previous/next message · Alt+1…0…-: speak last 11 messages"
        ),
    },
    "status.chat_opened": {"de": "Chat: {title}", "en": "Chat: {title}"},
    "status.starting": {"de": "Starte …", "en": "Starting …"},
    "status.ollama_error": {"de": "Ollama-Fehler: {err}", "en": "Ollama error: {err}"},
    "status.no_models": {"de": "Kein Modell installiert.", "en": "No model installed."},
    "status.active_model": {"de": "Aktives Modell: {model}", "en": "Active model: {model}"},

    # --- toolbar ---
    "toolbar.model_for_chat": {
        "de": "Modell für aktuellen Chat:",
        "en": "Model for current chat:",
    },
    "toolbar.model_name_a11y": {
        "de": "Modell für aktuellen Chat",
        "en": "Model for current chat",
    },
    "toolbar.connection_label": {
        "de": "Verbindung: {host} · nur lokal",
        "en": "Connection: {host} · local only",
    },
    "toolbar.connection_tooltip": {
        "de": (
            "FlameChat spricht ausschließlich mit diesem lokalen Ollama-Endpoint. "
            "Der Host wurde beim Start als Loopback-Adresse validiert."
        ),
        "en": (
            "FlameChat talks to this local Ollama endpoint only. The host was "
            "validated as a loopback address at startup."
        ),
    },

    # --- chat panel ---
    "chat.transcript_label": {"de": "Gesprächsverlauf", "en": "Conversation"},
    "chat.empty_state": {
        "de": (
            "Noch keine Nachrichten. Tippe unten deine Nachricht ein und "
            "drücke Enter zum Senden (Umschalt+Enter für eine neue Zeile)."
        ),
        "en": (
            "No messages yet. Type your message below and press Enter to "
            "send (Shift+Enter for a new line)."
        ),
    },
    "chat.input_label": {
        "de": "Nachricht (Enter zum Senden, Umschalt+Enter für neue Zeile)",
        "en": "Message (Enter to send, Shift+Enter for a new line)",
    },
    "chat.input_hint": {
        "de": "Frag etwas oder beschreibe deine Coding-Aufgabe …",
        "en": "Ask something or describe your coding task …",
    },
    "chat.input_name": {"de": "Nachrichteneingabe", "en": "Message input"},
    "chat.attach": {"de": "Anhang …", "en": "Attach …"},
    "chat.attach_name": {
        "de": "Anhang auswählen",
        "en": "Choose attachment",
    },
    "chat.intent_dialog_title": {
        "de": "Anhang — was möchtest du tun?",
        "en": "Attachment — what would you like to do?",
    },
    "chat.intent_dialog_body": {
        "de": (
            "Wähle ausdrücklich, was FlameChat mit der nächsten Datei "
            "machen soll. Jede Option öffnet danach einen Dateidialog mit "
            "dem passenden Typfilter."
        ),
        "en": (
            "Pick what you want FlameChat to do with the next file. "
            "Each option opens a file picker filtered to the right type."
        ),
    },
    "chat.intent_cancel": {"de": "Abbrechen", "en": "Cancel"},
    # Popup-menu items — explicit intents so the model never has to
    # guess whether an mp3 should be transcribed or technically analysed.
    "chat.attach_menu_image": {
        "de": "Bilder &beschreiben …",
        "en": "&Describe images …",
    },
    "chat.attach_menu_analyse": {
        "de": "Audio technisch &analysieren …",
        "en": "Technical audio &analysis …",
    },
    "chat.attach_menu_transcribe": {
        "de": "Audio &transkribieren …",
        "en": "&Transcribe audio …",
    },
    "chat.attach_menu_transcribe_summary": {
        "de": "Audio transkribieren &und zusammenfassen …",
        "en": "Transcribe &and summarise audio …",
    },
    "chat.attach_menu_text": {
        "de": "Text- oder Quelltext-Dateien an&hängen …",
        "en": "Attach &text or source files …",
    },
    "chat.attach_dialog_image": {
        "de": "Bilder auswählen (bis zu 3)",
        "en": "Pick images (up to 3)",
    },
    "chat.attach_dialog_audio": {
        "de": "Audio-Dateien auswählen (bis zu 3)",
        "en": "Pick audio files (up to 3)",
    },
    "chat.attach_dialog_text": {
        "de": "Text- oder Quelltext-Dateien auswählen (bis zu 3)",
        "en": "Pick text or source files (up to 3)",
    },
    "chat.attach_wildcard_image": {
        "de": (
            "Bilder|*.png;*.jpg;*.jpeg;*.gif;*.bmp;*.webp;*.heic;*.tiff|"
            "Alle Dateien|*.*"
        ),
        "en": (
            "Images|*.png;*.jpg;*.jpeg;*.gif;*.bmp;*.webp;*.heic;*.tiff|"
            "All files|*.*"
        ),
    },
    "chat.attach_wildcard_audio": {
        "de": (
            "Audio|*.wav;*.mp3;*.m4a;*.aac;*.flac;*.ogg;*.opus;*.aiff|"
            "Alle Dateien|*.*"
        ),
        "en": (
            "Audio|*.wav;*.mp3;*.m4a;*.aac;*.flac;*.ogg;*.opus;*.aiff|"
            "All files|*.*"
        ),
    },
    "chat.attach_wildcard_text": {
        "de": (
            "Text & Quelltext|"
            "*.txt;*.md;*.markdown;*.rst;*.log;*.csv;*.tsv;"
            "*.json;*.yaml;*.yml;*.toml;*.ini;*.cfg;*.conf;"
            "*.html;*.htm;*.xml;*.css;*.svg;"
            "*.py;*.pyi;*.js;*.jsx;*.ts;*.tsx;*.mjs;*.cjs;"
            "*.c;*.h;*.cpp;*.hpp;*.cc;*.cxx;*.rs;*.go;*.java;"
            "*.swift;*.kt;*.rb;*.pl;*.sh;*.bash;*.zsh;*.fish;"
            "*.sql;*.r;*.lua;*.tex;*.bat;*.ps1|"
            "Alle Dateien|*.*"
        ),
        "en": (
            "Text & source|"
            "*.txt;*.md;*.markdown;*.rst;*.log;*.csv;*.tsv;"
            "*.json;*.yaml;*.yml;*.toml;*.ini;*.cfg;*.conf;"
            "*.html;*.htm;*.xml;*.css;*.svg;"
            "*.py;*.pyi;*.js;*.jsx;*.ts;*.tsx;*.mjs;*.cjs;"
            "*.c;*.h;*.cpp;*.hpp;*.cc;*.cxx;*.rs;*.go;*.java;"
            "*.swift;*.kt;*.rb;*.pl;*.sh;*.bash;*.zsh;*.fish;"
            "*.sql;*.r;*.lua;*.tex;*.bat;*.ps1|"
            "All files|*.*"
        ),
    },
    "chat.attach_too_many": {
        "de": (
            "Du hast {count} Dateien ausgewählt. FlameChat verarbeitet "
            "höchstens {limit} pro Vorgang, damit das Modell noch sinnvoll "
            "antworten kann.\n\nWähle eine kleinere Auswahl und hänge den "
            "Rest danach in einem zweiten Schritt an."
        ),
        "en": (
            "You picked {count} files. FlameChat handles at most {limit} "
            "per action so the model can still respond sensibly.\n\n"
            "Pick a smaller batch and attach the rest in a second step."
        ),
    },
    "chat.attach_wrong_type_text": {
        "de": (
            "Eine der ausgewählten Dateien ist keine Textdatei. FlameChat "
            "erkennt Text an gängigen Endungen (.txt, .md, .json, .yaml, "
            "Programmcode usw.) sowie am MIME-Typ. Wähle ausschließlich "
            "Textdateien."
        ),
        "en": (
            "One of the selected files is not a text file. FlameChat "
            "recognises text by common extensions (.txt, .md, .json, "
            ".yaml, source code and so on) and by MIME type. Pick text "
            "files only."
        ),
    },
    "chat.attach_wrong_type_image": {
        "de": (
            "Die ausgewählte Datei sieht nicht nach einem Bild aus. "
            "FlameChat erkennt Bilder an den Dateiendungen PNG, JPG, "
            "JPEG, GIF, BMP, WebP, HEIC und TIFF. Wähle eine solche "
            "Datei, oder benutze die \u201eAudio\u201c-Aktion, falls du "
            "eigentlich Ton analysieren wolltest."
        ),
        "en": (
            "The selected file doesn't look like an image. FlameChat "
            "recognises images by the extensions PNG, JPG, JPEG, GIF, "
            "BMP, WebP, HEIC and TIFF. Pick one of those, or use the "
            "\u201cAudio\u201d action instead if you meant to analyse sound."
        ),
    },
    "chat.attach_wrong_type_audio": {
        "de": (
            "Die ausgewählte Datei sieht nicht nach einer Audiodatei "
            "aus. FlameChat erwartet WAV, MP3, M4A, AAC, FLAC, OGG, "
            "Opus oder AIFF. Konvertiere die Datei (z. B. mit Audacity) "
            "oder wähle direkt eine Audiodatei."
        ),
        "en": (
            "The selected file doesn't look like an audio file. "
            "FlameChat expects WAV, MP3, M4A, AAC, FLAC, OGG, Opus or "
            "AIFF. Convert the file (for instance with Audacity) or "
            "pick an audio file directly."
        ),
    },
    "chat.attach_error_title": {
        "de": "Anhang kann so nicht verwendet werden",
        "en": "Can't use that attachment",
    },
    "chat.no_vision_model_title": {
        "de": "Kein bildfähiges Modell bereit",
        "en": "No image-capable model ready",
    },
    "chat.no_vision_model_body": {
        "de": (
            "Für die Bildbeschreibung brauchst du ein Modell, das Bilder "
            "lesen kann — keines deiner installierten Modelle erfüllt das.\n\n"
            "So kommst du dran: öffne Einstellungen mit Cmd+, und lade im "
            "Reiter „Modelle“ eines der empfohlenen multimodalen Modelle. "
            "Gute Optionen sind Gemma 4, Gemma 3 (ab 4B) oder Llava. Nach "
            "dem Download kannst du erneut versuchen, das Bild anzuhängen."
        ),
        "en": (
            "Image description needs a model that can actually read images "
            "— none of your installed models qualifies.\n\n"
            "How to get one: open Preferences with Cmd+, and, in the "
            "“Models” tab, download one of the recommended multimodal "
            "models. Good picks are Gemma 4, Gemma 3 (4B and up) or Llava. "
            "Once it's downloaded, try the image attachment again."
        ),
    },
    "chat.attached_image_note": {
        "de": "Bilder werden beschrieben: {files}",
        "en": "Describing images: {files}",
    },
    "chat.attached_analyse_note": {
        "de": "Audio wird technisch analysiert: {file}",
        "en": "Running technical audio analysis: {file}",
    },
    "chat.attached_transcribe_note": {
        "de": "Audio wird transkribiert: {file}",
        "en": "Transcribing audio: {file}",
    },
    "chat.attached_transcribe_summary_note": {
        "de": "Audio wird transkribiert und zusammengefasst: {file}",
        "en": "Transcribing and summarising audio: {file}",
    },
    "chat.attached_text_note": {
        "de": "Textdateien als Kontext angehängt: {files}",
        "en": "Text files attached as context: {files}",
    },
    "chat.attached_text_header": {
        "de": "Ich hänge dir folgende Datei(en) als Kontext an, bitte berücksichtige sie bei der nächsten Antwort.",
        "en": "I'm attaching the following file(s) as context — please take them into account for the next answer.",
    },
    "chat.staging_label": {
        "de": "Wird mitgesendet:",
        "en": "Attached to next message:",
    },
    "chat.staging_remove": {
        "de": "{name} entfernen",
        "en": "Remove {name}",
    },
    "chat.staging_remove_short": {"de": "Entfernen", "en": "Remove"},
    "chat.staged_image_marker": {
        "de": "[Angehängtes Bild: {files}]",
        "en": "[Attached image(s): {files}]",
    },
    "chat.staged_text_section": {
        "de": "--- Datei: {name} ({size}) ---\n{content}",
        "en": "--- File: {name} ({size}) ---\n{content}",
    },
    "chat.default_image_prompt": {
        "de": (
            "Beschreibe bitte ausführlich, was auf dem bzw. den angehängten "
            "Bildern zu sehen ist."
        ),
        "en": (
            "Please describe in detail what is visible in the attached image(s)."
        ),
    },
    "chat.empty_body_default": {
        "de": "(Bitte schau dir die angehängten Dateien an.)",
        "en": "(Please take a look at the attached files.)",
    },
    "chat.read_error": {
        "de": "Konnte Textdatei nicht lesen: {name}",
        "en": "Couldn't read text file: {name}",
    },
    "chat.transcribing": {
        "de": "Transkribiere Audio …",
        "en": "Transcribing audio …",
    },
    "chat.analysing": {
        "de": "Technische Analyse des Audios …",
        "en": "Analysing audio …",
    },
    "chat.summarising": {
        "de": "Zusammenfassung wird erstellt …",
        "en": "Summarising …",
    },
    "chat.attachment_saved_title": {
        "de": "Ergebnis speichern",
        "en": "Save result",
    },
    "chat.attachment_saved_prompt": {
        "de": (
            "Das Ergebnis ist {chars} Zeichen lang und würde den Chat "
            "überladen. In welche Datei möchtest du es speichern?"
        ),
        "en": (
            "The result is {chars} characters long and would overwhelm "
            "the chat. Where would you like to save it?"
        ),
    },
    "chat.attachment_saved_default": {
        "de": "{stem}-{what}.txt",
        "en": "{stem}-{what}.txt",
    },
    "chat.what_transcript": {"de": "Transkript", "en": "transcript"},
    "chat.what_summary": {"de": "Zusammenfassung", "en": "summary"},
    "chat.what_analysis": {"de": "Audioanalyse", "en": "audio-analysis"},
    "chat.send": {"de": "Senden", "en": "Send"},
    "chat.send_name": {"de": "Nachricht senden", "en": "Send message"},
    "chat.abort": {"de": "Abbrechen", "en": "Cancel"},
    "chat.abort_name": {"de": "Antwort abbrechen", "en": "Cancel response"},
    "chat.progress_name": {"de": "Fortschritt der Antwort", "en": "Response progress"},
    "chat.status_ready": {"de": "Bereit", "en": "Ready"},
    "chat.status_ready_new": {
        "de": "Neuer Chat — tippe deine erste Nachricht.",
        "en": "New chat — type your first message.",
    },
    "chat.empty_submit": {
        "de": "Leere Nachricht — nichts gesendet.",
        "en": "Empty message — nothing sent.",
    },
    "chat.thinking": {
        "de": "Assistant denkt nach … (Modell: {model})",
        "en": "Assistant is thinking … (model: {model})",
    },
    "chat.writing": {
        "de": "Assistant schreibt … {tokens} Tokens ({pct} % von {max})",
        "en": "Assistant writing … {tokens} tokens ({pct} % of {max})",
    },
    "chat.aborting": {"de": "Breche Antwort ab …", "en": "Cancelling response …"},
    "chat.aborted": {"de": "Antwort abgebrochen.", "en": "Response cancelled."},
    "chat.received": {
        "de": "Antwort empfangen. Bereit für die nächste Nachricht.",
        "en": "Response received. Ready for the next message.",
    },
    "chat.error": {"de": "Fehler: {err}", "en": "Error: {err}"},
    "chat.error_box_title": {
        "de": "Antwort konnte nicht fertig generiert werden",
        "en": "Couldn't finish generating the response",
    },
    "chat.error_box_body": {
        "de": (
            "Die Anfrage an Ollama wurde abgebrochen, bevor die Antwort "
            "vollständig war.\n\n"
            "Häufige Ursachen: Ollama ist während der Antwort abgestürzt, "
            "der Arbeitsspeicher war nicht ausreichend für das gewählte "
            "Modell, oder die Verbindung wurde unterbrochen.\n\n"
            "Probiere Folgendes:\n"
            " • Klicke nochmal auf die Nachricht und wähle „Neu generieren“.\n"
            " • Wechsle in den Einstellungen zu einem kleineren Modell.\n"
            " • Beende FlameChat und starte es neu.\n\n"
            "Technische Details: {err}"
        ),
        "en": (
            "The request to Ollama was cut short before the response "
            "finished.\n\n"
            "Common causes: Ollama crashed mid-response, your machine "
            "ran out of memory for the chosen model, or the connection "
            "was interrupted.\n\n"
            "Try the following:\n"
            " • Right-click the message and pick “Regenerate”.\n"
            " • Switch to a smaller model in Preferences.\n"
            " • Quit FlameChat and start it again.\n\n"
            "Technical details: {err}"
        ),
    },
    "chat.no_model_title": {
        "de": "Noch kein Modell bereit",
        "en": "No model ready yet",
    },
    "chat.no_model_body": {
        "de": (
            "Für diesen Chat ist noch kein Sprachmodell ausgewählt — "
            "entweder ist keins installiert, oder das vorher benutzte "
            "wurde entfernt.\n\n"
            "So bekommst du eines: öffne Einstellungen mit Cmd+, und "
            "wähle im Reiter „Modelle“ ein empfohlenes Modell zum "
            "Herunterladen. Nach dem Download kannst du oben im Chat-"
            "Fenster das Modell für diesen Chat auswählen."
        ),
        "en": (
            "No language model is selected for this chat — either none is "
            "installed, or the one you picked earlier is no longer there.\n\n"
            "To get one: open Preferences with Cmd+, and pick a recommended "
            "model in the “Models” tab. Once the download is done, choose "
            "the model in the dropdown at the top of the chat window."
        ),
    },
    "chat.empty_answer": {"de": "(Leere Antwort)", "en": "(Empty response)"},
    "chat.aborted_answer": {"de": "(Antwort abgebrochen)", "en": "(Response cancelled)"},
    "chat.aborted_suffix": {"de": "[abgebrochen]", "en": "[cancelled]"},

    # --- message context menu ---
    "msg.role_user": {"de": "Du", "en": "You"},
    "msg.role_assistant": {"de": "Assistant", "en": "Assistant"},
    "msg.role_system": {"de": "System", "en": "System"},
    "msg.a11y_body_suffix": {"de": "Inhalt", "en": "content"},
    "msg.a11y_position": {"de": "Nachricht {i} von {n}.", "en": "Message {i} of {n}."},
    "msg.menu_copy": {
        "de": "Nachricht &kopieren\tCtrl+C",
        "en": "&Copy message\tCtrl+C",
    },
    "msg.menu_regen": {
        "de": "Neu &generieren\tCtrl+R",
        "en": "&Regenerate\tCtrl+R",
    },
    "msg.menu_save": {"de": "Als &TXT speichern …", "en": "Save as &TXT …"},
    "msg.save_dialog_title": {"de": "Nachricht speichern", "en": "Save message"},
    "msg.save_wildcard": {
        "de": "Textdatei (*.txt)|*.txt|Alle Dateien|*.*",
        "en": "Text file (*.txt)|*.txt|All files|*.*",
    },
    "msg.save_default_file": {
        "de": "{role}_nachricht.txt",
        "en": "{role}_message.txt",
    },
    "msg.save_error_title": {
        "de": "Datei konnte nicht gespeichert werden",
        "en": "Couldn't save the file",
    },
    "msg.save_error_body": {
        "de": (
            "FlameChat konnte die Datei nicht schreiben.\n\n"
            "Meist liegt das daran, dass der gewählte Ordner schreib­geschützt "
            "ist oder gar nicht existiert. Wähle einen anderen Ordner "
            "(z. B. deinen Schreibtisch oder Dokumente-Ordner) und versuche "
            "es erneut.\n\n"
            "Technische Details: {err}"
        ),
        "en": (
            "FlameChat couldn't write the file.\n\n"
            "Usually this means the selected folder is read-only or no "
            "longer exists. Pick a different folder (your Desktop or "
            "Documents folder is a safe bet) and try again.\n\n"
            "Technical details: {err}"
        ),
    },

    # --- announcements (screen reader) ---
    "say.msg_sent": {
        "de": "Nachricht gesendet. Assistant denkt nach.",
        "en": "Message sent. Assistant is thinking.",
    },
    "say.msg_received": {"de": "Antwort empfangen.", "en": "Response received."},
    "say.cancelling": {"de": "Antwort wird abgebrochen.", "en": "Cancelling response."},
    "say.cancelled": {"de": "Antwort abgebrochen.", "en": "Response cancelled."},
    "say.request_error": {
        "de": "Fehler bei der Anfrage.",
        "en": "Request failed.",
    },
    "say.copied": {"de": "Nachricht kopiert.", "en": "Message copied."},
    "say.saved": {
        "de": "Nachricht als Textdatei gespeichert.",
        "en": "Message saved as text file.",
    },
    "say.save_failed": {"de": "Speichern fehlgeschlagen.", "en": "Save failed."},
    "say.chat_opened": {"de": "Chat geöffnet: {title}", "en": "Chat opened: {title}"},
    "say.chat_created": {"de": "Neuer Chat angelegt.", "en": "New chat created."},
    "say.chat_deleted": {"de": "Chat gelöscht.", "en": "Chat deleted."},
    "say.chat_list_focus": {"de": "Chat-Liste: {title}", "en": "Chat list: {title}"},
    "say.no_messages_in_chat": {
        "de": "Keine Nachrichten in diesem Chat.",
        "en": "No messages in this chat.",
    },
    "say.only_n_messages": {
        "de": "Dieser Chat hat nur {count} Nachrichten.",
        "en": "This chat only has {count} messages.",
    },

    # --- chat list ---
    "list.header": {"de": "Chats", "en": "Chats"},
    "list.name_a11y": {"de": "Chat-Liste", "en": "Chat list"},
    "list.col_title": {"de": "Titel", "en": "Title"},
    "list.col_model": {"de": "Modell", "en": "Model"},
    "list.col_updated": {"de": "Zuletzt", "en": "Updated"},
    "list.no_model_cell": {"de": "(kein Modell)", "en": "(no model)"},
    "list.new_chat": {"de": "+ Neuer Chat", "en": "+ New chat"},
    "list.new_chat_name": {"de": "Neuen Chat anlegen", "en": "Create new chat"},
    "list.delete": {"de": "Löschen", "en": "Delete"},
    "list.delete_name": {"de": "Ausgewählten Chat löschen", "en": "Delete selected chat"},
    "list.default_title": {"de": "Neuer Chat", "en": "New chat"},
    "list.confirm_delete_title": {"de": "Chat löschen", "en": "Delete chat"},
    "list.confirm_delete_body": {
        "de": "Chat \u201e{title}\u201c wirklich löschen? Das kann nicht rückgängig gemacht werden.",
        "en": "Really delete chat \u201c{title}\u201d? This cannot be undone.",
    },
    "list.menu_open": {"de": "Chat &öffnen", "en": "&Open chat"},
    "list.menu_delete": {"de": "&Löschen\tEntf", "en": "&Delete\tDel"},

    # --- settings dialog ---
    "prefs.title": {"de": "Einstellungen", "en": "Preferences"},
    "prefs.name_a11y": {"de": "Einstellungen", "en": "Preferences"},
    "prefs.notebook_name": {"de": "Einstellungen-Reiter", "en": "Preferences tabs"},
    "prefs.tab_models": {"de": "Modelle", "en": "Models"},
    "prefs.tab_sounds": {"de": "Sounds", "en": "Sounds"},
    "prefs.tab_chats": {"de": "Chats", "en": "Chats"},
    "prefs.tab_general": {"de": "Allgemein", "en": "General"},
    "prefs.tab_about": {"de": "Info", "en": "About"},
    "prefs.close": {"de": "Schließen", "en": "Close"},
    "prefs.close_name": {"de": "Einstellungen schließen", "en": "Close preferences"},

    "prefs.sounds.heading": {"de": "Akustisches Feedback", "en": "Audio feedback"},
    "prefs.sounds.main_toggle": {
        "de": "Send- und Empfangs-Sounds abspielen",
        "en": "Play send and receive sounds",
    },
    "prefs.sounds.typing_toggle": {
        "de": "Tipp-Geräusche während der Antwort-Generierung",
        "en": "Typing sound while the assistant writes",
    },
    "prefs.sounds.test_send": {"de": "Send-Sound testen", "en": "Test send sound"},
    "prefs.sounds.test_receive": {
        "de": "Empfangs-Sound testen",
        "en": "Test receive sound",
    },
    "prefs.sounds.test_typing": {"de": "Tipp-Geräusch testen", "en": "Test typing sound"},
    "prefs.sounds.note": {
        "de": (
            "Hinweis: Während das Modell tippt, läuft eine zufällig "
            "gewählte Tipp-Aufnahme im Loop. Beim nächsten Durchlauf "
            "wählt FlameChat automatisch eine andere Variante, damit "
            "es nicht repetitiv wirkt."
        ),
        "en": (
            "Note: while the model is writing, a randomly selected "
            "typing loop plays in the background. The next run picks "
            "a different variant so it does not feel repetitive."
        ),
    },

    "prefs.chats.heading": {"de": "Chat-Verhalten", "en": "Chat behaviour"},
    "prefs.chats.auto_create": {
        "de": (
            "Nach dem Löschen des letzten Chats und beim ersten Start "
            "automatisch einen neuen leeren Chat anlegen (empfohlen)"
        ),
        "en": (
            "Create a new empty chat on first launch and after the last "
            "chat is deleted (recommended)"
        ),
    },
    "prefs.chats.note": {
        "de": (
            "Ist diese Option aus, zeigt FlameChat einen leeren Bereich "
            "an, wenn keine Chats existieren — du legst dann manuell "
            "\u201e+ Neuer Chat\u201c einen an."
        ),
        "en": (
            "When this option is off, FlameChat shows an empty pane if "
            "no chats exist — you then create one manually through "
            "\u201c+ New chat\u201d."
        ),
    },

    "prefs.general.heading": {"de": "Allgemein", "en": "General"},
    "prefs.general.theme_label": {"de": "Erscheinungsbild:", "en": "Appearance:"},
    "prefs.general.theme_name": {"de": "Erscheinungsbild", "en": "Appearance"},
    "prefs.general.theme_dark": {"de": "Dunkel", "en": "Dark"},
    "prefs.general.theme_light": {"de": "Hell", "en": "Light"},
    "prefs.general.theme_note": {
        "de": (
            "FlameChat startet standardmäßig im dunklen Modus. Die Umschaltung "
            "greift sofort; einige Nischen-Steuerelemente (etwa die Menüleiste) "
            "übernehmen die neue Farbe erst beim nächsten Start."
        ),
        "en": (
            "FlameChat starts in dark mode by default. The switch takes "
            "effect immediately; a few niche controls (the menu bar, for "
            "instance) only pick up the new colour at the next launch."
        ),
    },
    "prefs.general.language_label": {"de": "Sprache:", "en": "Language:"},
    "prefs.general.language_name": {"de": "Sprache", "en": "Language"},
    "prefs.general.language_note": {
        "de": (
            "Die Sprachumstellung wird beim nächsten Start von FlameChat "
            "übernommen."
        ),
        "en": (
            "The language change takes effect the next time FlameChat "
            "starts."
        ),
    },
    "prefs.general.num_predict_label": {
        "de": "Maximale Antwortlänge (Tokens):",
        "en": "Maximum reply length (tokens):",
    },
    "prefs.general.num_predict_name": {
        "de": "Maximale Antwortlänge in Tokens",
        "en": "Maximum reply length in tokens",
    },
    "prefs.general.num_predict_note": {
        "de": (
            "Obergrenze, bis zu der das Modell eine einzelne Antwort "
            "produzieren darf. Nur Nenner für die Prozent­anzeige — das "
            "Modell hört früher auf, sobald es fertig ist."
        ),
        "en": (
            "Upper limit on how long a single response may get. Only a "
            "denominator for the progress bar — the model stops sooner "
            "once it is actually done."
        ),
    },
    "prefs.general.whisper_label": {
        "de": "Transkriptions-Modell (Whisper):",
        "en": "Transcription model (Whisper):",
    },
    "prefs.general.whisper_name": {
        "de": "Whisper-Modellgröße",
        "en": "Whisper model size",
    },
    "prefs.general.whisper_note": {
        "de": (
            "Modell, das beim Transkribieren von Audio verwendet wird. "
            "Größer = genauer, aber langsamer und speicherhungriger. "
            "‚small' ist ein guter Kompromiss."
        ),
        "en": (
            "Model used when transcribing audio. Larger sizes are more "
            "accurate but slower and hungrier for memory. ‘small' is a "
            "good balance."
        ),
    },
    "prefs.general.inline_limit_label": {
        "de": "Direkt im Chat anzeigen, bis (Zeichen):",
        "en": "Show inline in chat up to (characters):",
    },
    "prefs.general.inline_limit_name": {
        "de": "Maximale Länge inline im Chat",
        "en": "Maximum inline length in chat",
    },
    "prefs.general.inline_limit_note": {
        "de": (
            "Transkripte und Analysen unterhalb dieser Länge erscheinen "
            "direkt im Chat. Längere Ergebnisse werden als Textdatei "
            "angeboten."
        ),
        "en": (
            "Transcripts and analyses up to this length appear inline "
            "in the chat. Longer results are offered as a text file "
            "save instead."
        ),
    },

    "prefs.about.name": {"de": "FlameChat", "en": "FlameChat"},
    "prefs.about.version": {"de": "Version {version}", "en": "Version {version}"},
    "prefs.about.tagline": {
        "de": "Zugänglicher, komplett lokaler AI-Chat — für Gespräche und Coding.",
        "en": "Accessibility-first, fully local AI chat — for conversations and coding.",
    },
    "prefs.about.privacy_heading": {"de": "Datenschutz", "en": "Privacy"},
    "prefs.about.privacy_body": {
        "de": (
            "Außer dem einmaligen Ollama-Download und einem vom Nutzer "
            "angestoßenen Modell-Download verlassen keine Daten den "
            "Rechner. Die Verbindung zum lokalen Ollama-Server wird beim "
            "Start als Loopback-Adresse validiert."
        ),
        "en": (
            "Apart from the one-time Ollama download and user-initiated "
            "model downloads, no data ever leaves your machine. The "
            "connection to the local Ollama server is validated as a "
            "loopback address at startup."
        ),
    },
    "prefs.about.shortcuts_heading": {
        "de": "Tastenkürzel",
        "en": "Keyboard shortcuts",
    },
    "prefs.about.shortcuts_body": {
        "de": (
            "Cmd+N: Neuer Chat · Cmd+M: Modelle · Cmd+,: Einstellungen · "
            "Cmd+1: Chat-Liste · Cmd+2: Nachrichteneingabe · "
            "Ctrl+Cmd+Pfeil hoch/runter: zwischen Nachrichten navigieren · "
            "Alt+1 bis Alt+0 bzw. Alt+ß: die letzten 11 Nachrichten vorlesen lassen · "
            "Enter: senden · Umschalt+Enter: neue Zeile · "
            "Esc: Antwort abbrechen · Cmd+C: Nachricht kopieren."
        ),
        "en": (
            "Cmd+N: new chat · Cmd+M: models · Cmd+,: preferences · "
            "Cmd+1: chat list · Cmd+2: message input · "
            "Ctrl+Cmd+Up/Down: navigate between messages · "
            "Alt+1 … Alt+0 … Alt+-: speak the last 11 messages · "
            "Enter: send · Shift+Enter: new line · "
            "Esc: cancel response · Cmd+C: copy message."
        ),
    },

    # --- prepare dialog (first-launch ollama download) ---
    "prepare.title": {
        "de": "FlameChat wird vorbereitet",
        "en": "Preparing FlameChat",
    },
    "prepare.headline": {
        "de": "Einen Moment, Ollama wird eingerichtet.",
        "en": "Just a moment — setting up Ollama.",
    },
    "prepare.phase_start": {"de": "Starte …", "en": "Starting …"},
    "prepare.cancel": {"de": "Abbrechen", "en": "Cancel"},
    "prepare.cancel_name": {"de": "Abbrechen", "en": "Cancel"},
    "prepare.phase_ready": {"de": "Bereit.", "en": "Ready."},
    "prepare.phase_aborting": {"de": "Abbruch …", "en": "Cancelling …"},
    "prepare.fail_title": {
        "de": "Ollama konnte nicht vorbereitet werden",
        "en": "Couldn't prepare Ollama",
    },
    "prepare.fail_body": {
        "de": (
            "FlameChat kann ohne einen funktionierenden Ollama-Dienst "
            "nicht starten, und die Einrichtung ist auf einen Fehler "
            "gelaufen.\n\n"
            "Details: {err}\n\n"
            "Was du tun kannst:\n"
            " • Starte FlameChat erneut — manchmal hilft ein zweiter "
            "Versuch, besonders nach Netzwerk-Problemen.\n"
            " • Installiere Ollama von Hand: https://ollama.com/download. "
            "Danach öffnest du FlameChat und der Start sollte klappen.\n"
            " • Prüfe, ob genug Speicherplatz frei ist und deine Internet-"
            "Verbindung stabil ist."
        ),
        "en": (
            "FlameChat can't start without a working Ollama service, and "
            "setup ran into an error.\n\n"
            "Details: {err}\n\n"
            "What you can try:\n"
            " • Launch FlameChat again — a retry often helps, especially "
            "after network glitches.\n"
            " • Install Ollama manually: https://ollama.com/download, "
            "then reopen FlameChat.\n"
            " • Make sure you have enough free disk space and a stable "
            "internet connection."
        ),
    },
    "prepare.ollama_running": {
        "de": "Ollama ist bereits aktiv",
        "en": "Ollama is already running",
    },
    "prepare.ollama_installing": {
        "de": "Ollama wird installiert …",
        "en": "Installing Ollama …",
    },
    "prepare.ollama_downloading": {
        "de": "Lade Ollama-Installer herunter …",
        "en": "Downloading Ollama installer …",
    },
    "prepare.ollama_mounting": {
        "de": "Entpacke Ollama-DMG …",
        "en": "Opening the Ollama DMG …",
    },
    "prepare.ollama_copying": {
        "de": "Kopiere Ollama nach /Applications …",
        "en": "Copying Ollama to /Applications …",
    },
    "prepare.ollama_win_installer": {
        "de": "Starte Ollama-Installer …",
        "en": "Running the Ollama installer …",
    },
    "prepare.ollama_linux_script": {
        "de": "Starte Ollama-Installations-Skript …",
        "en": "Running the Ollama install script …",
    },
    "prepare.ollama_starting": {"de": "Starte Ollama …", "en": "Starting Ollama …"},
    "prepare.ollama_waiting": {
        "de": "Warte, bis Ollama bereit ist …",
        "en": "Waiting for Ollama to be ready …",
    },
    "prepare.ollama_ready": {"de": "Bereit", "en": "Ready"},
    "prepare.note": {
        "de": (
            "Falls Ollama noch nicht installiert ist, lädt FlameChat den "
            "offiziellen Installer (~150 MB) und richtet Ollama system­weit "
            "ein — danach nutzt sowohl die App als auch dein Terminal "
            "dieselbe Installation. Nichts verlässt den Rechner mehr, außer "
            "du ziehst explizit ein Sprachmodell."
        ),
        "en": (
            "If Ollama is not yet installed, FlameChat fetches the "
            "official installer (~150 MB) and sets it up system-wide so "
            "the app and your terminal share one install. After that no "
            "data leaves your machine unless you explicitly download a "
            "language model."
        ),
    },

    # --- models panel ---
    "models.installed_label": {"de": "Installierte Modelle", "en": "Installed models"},
    "models.installed_name": {"de": "Installierte Modelle", "en": "Installed models"},
    "models.suggestions_label": {
        "de": "Empfohlene Modelle für deine Hardware",
        "en": "Recommended models for your hardware",
    },
    "models.suggestions_name": {"de": "Empfohlene Modelle", "en": "Recommended models"},
    "models.pull_button": {
        "de": "Ausgewähltes Modell herunterladen",
        "en": "Download selected model",
    },
    "models.pull_name": {
        "de": "Ausgewähltes Modell herunterladen",
        "en": "Download selected model",
    },
    "models.progress_name": {"de": "Download-Fortschritt", "en": "Download progress"},
    "models.progress_status_name": {"de": "Download-Status", "en": "Download status"},
    "models.hardware_name": {"de": "Erkannte Hardware", "en": "Detected hardware"},
    "models.ollama_unreachable_title": {
        "de": "Verbindung zu Ollama unterbrochen",
        "en": "Connection to Ollama lost",
    },
    "models.ollama_unreachable_body": {
        "de": (
            "FlameChat kann Ollama im Moment nicht erreichen, um die "
            "installierten Modelle anzuzeigen.\n\n"
            "Wahrscheinlich ist der Ollama-Dienst gerade nicht aktiv "
            "(z. B. nach einem System-Schlaf oder wenn jemand das "
            "Menüleisten-Symbol geschlossen hat).\n\n"
            "So geht's weiter: beende FlameChat und öffne es neu — "
            "Ollama wird dann automatisch wieder gestartet.\n\n"
            "Technische Details: {err}"
        ),
        "en": (
            "FlameChat can't reach Ollama right now to list your "
            "installed models.\n\n"
            "Most likely the Ollama service isn't running (for example "
            "after a sleep/wake cycle, or if someone quit it from its "
            "menu bar icon).\n\n"
            "Next step: quit and reopen FlameChat — it will bring "
            "Ollama back up automatically.\n\n"
            "Technical details: {err}"
        ),
    },
    "models.pull_starting": {
        "de": "Starte Download von {model} …",
        "en": "Starting download of {model} …",
    },
    "models.pull_done": {
        "de": "{model} erfolgreich heruntergeladen.",
        "en": "{model} downloaded successfully.",
    },
    "models.pull_error_title": {
        "de": "Modell-Download ist fehlgeschlagen",
        "en": "Model download failed",
    },
    "models.pull_error_body": {
        "de": (
            "Der Download konnte nicht abgeschlossen werden.\n\n"
            "Häufige Ursachen: unterbrochene Internetverbindung, zu wenig "
            "freier Speicherplatz auf der Festplatte, oder das gewählte "
            "Modell ist momentan auf Ollamas Servern nicht verfügbar.\n\n"
            "Versuche Folgendes:\n"
            " • Prüfe die Internetverbindung und starte den Download erneut.\n"
            " • Schaue unter „Über diesen Mac“ → „Speicher“ nach, ob "
            "genug Platz frei ist.\n"
            " • Wähle zunächst ein kleineres Modell als Test.\n\n"
            "Technische Details: {err}"
        ),
        "en": (
            "The download didn't finish.\n\n"
            "Common causes: interrupted internet connection, not enough "
            "free disk space, or the requested model is temporarily "
            "unavailable on Ollama's servers.\n\n"
            "Try the following:\n"
            " • Check your internet connection and retry the download.\n"
            " • Make sure you have enough free disk space.\n"
            " • Try a smaller model first as a sanity check.\n\n"
            "Technical details: {err}"
        ),
    },
    "models.pull_progress": {
        "de": "{status}: {done} / {total} MB ({pct} %)",
        "en": "{status}: {done} / {total} MB ({pct} %)",
    },
    "models.hw_os": {"de": "Betriebssystem: {os}", "en": "Operating system: {os}"},
    "models.hw_cpu": {
        "de": "CPU: {phys} Kerne ({log} logisch)",
        "en": "CPU: {phys} cores ({log} logical)",
    },
    "models.hw_ram": {"de": "RAM: {ram:.1f} GB", "en": "RAM: {ram:.1f} GB"},
    "models.hw_apple_gpu": {
        "de": "GPU: {name} (Unified Memory, ca. {vram:.1f} GB nutzbar)",
        "en": "GPU: {name} (unified memory, ~{vram:.1f} GB usable)",
    },
    "models.hw_discrete_gpu": {
        "de": "GPU: {name} · {vram:.1f} GB VRAM",
        "en": "GPU: {name} · {vram:.1f} GB VRAM",
    },
    "models.hw_no_gpu": {
        "de": "GPU: keine dedizierte GPU erkannt — Inferenz läuft auf der CPU",
        "en": "GPU: no dedicated GPU detected — inference runs on the CPU",
    },
    "models.suggestion_row": {
        "de": "{name}  ·  ~{size:.1f} GB Download  ·  ~{ram:.0f} GB RAM  ·  {desc}",
        "en": "{name}  ·  ~{size:.1f} GB download  ·  ~{ram:.0f} GB RAM  ·  {desc}",
    },
    "models.installed_row": {
        "de": "{name}  ·  {size:.1f} GB  ·  {params}  ·  {quant}",
        "en": "{name}  ·  {size:.1f} GB  ·  {params}  ·  {quant}",
    },
}


def set_language(lang: Language) -> None:
    global _current
    _current = lang


def current_language() -> Language:
    return _current


def t(key: str, **kwargs) -> str:
    """Translate ``key`` using the current language.

    ``kwargs`` are substituted via str.format if the translation uses
    placeholders. Unknown keys render as the key itself so developers
    spot the typo at a glance.
    """
    entry = TRANSLATIONS.get(key)
    if entry is None:
        return key
    text = entry.get(_current) or entry.get("en") or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text
