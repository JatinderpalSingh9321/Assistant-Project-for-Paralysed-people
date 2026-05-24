from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if '__file__' in globals() else os.getcwd()
PDF_PATH = os.path.join(PROJECT_ROOT, 'NavTools_Command_List.pdf')

NAVY = colors.HexColor('#081425')
CYAN = colors.HexColor('#00f5c8')
BLACK = colors.black
WHITE = colors.white
CARD2 = colors.HexColor('#152031')

styles = getSampleStyleSheet()
base = dict(fontName='Helvetica', fontSize=10, leading=15, textColor=BLACK, spaceAfter=6, spaceBefore=3)

title_style = ParagraphStyle('title', **{**base, 'fontSize': 22, 'leading': 28, 'alignment': 1, 'fontName': 'Helvetica-Bold', 'textColor': NAVY, 'spaceAfter': 20})
h2_style = ParagraphStyle('h2', **{**base, 'fontSize': 14, 'leading': 18, 'fontName': 'Helvetica-Bold', 'textColor': NAVY, 'spaceBefore': 12, 'spaceAfter': 8})
normal_style = ParagraphStyle('normal', **base)
bullet_style = ParagraphStyle('bullet', **{**base, 'leftIndent': 15, 'bulletIndent': 5, 'spaceAfter': 4})
note_style = ParagraphStyle('note', **{**base, 'fontName': 'Helvetica-Oblique', 'textColor': colors.gray})

commands = {
    'Browser & Tab Navigation': [
        ('open google / open youtube', 'Launches browser to Google/YouTube.'),
        ('new tab / close tab', 'Opens/closes the current browser tab.'),
        ('next tab / previous tab', 'Switches to the next/previous browser tab.'),
        ('go back / go forward', 'Navigates back/forward one page.'),
        ('refresh page', 'Reloads the current page.'),
        ('click first result / click second link', 'Clicks the Nth link on the current web page.')
    ],
    'Local Application Launchers': [
        ('open calculator / open notepad', 'Launches specific applications.'),
        ('open task manager / open terminal', 'Launches system tools.'),
        ('open windows settings / open device manager', 'Launches settings panels.'),
        ('open word / excel / powerpoint / outlook', 'Launches Office apps.'),
        ('open steam / discord / spotify / vs code', 'Launches common software.'),
        ('open downloads / documents / desktop', 'Opens system folders.')
    ],
    'Windows & System Controls': [
        ('minimize window / maximize window', 'Changes the state of the active window.'),
        ('snap left / snap right / full screen', 'Snaps the window or toggles F11 full screen.'),
        ('scroll down / scroll up', 'Scrolls slightly up or down.'),
        ('page down / page up', 'Scrolls a full page.'),
        ('go to top / go to bottom', 'Jumps to the very top or bottom of the page.'),
        ('take screenshot', 'Opens the Windows Snip & Sketch overlay.'),
        ('lock screen', 'Instantly locks the Windows session.'),
        ('volume up / volume down / mute', 'System audio control.'),
        ('copy / paste / undo / redo / select all', 'Standard keyboard shortcuts (Ctrl+C, etc).')
    ],
    'Global Media Controls': [
        ('play / pause / play pause', 'Triggers the global Play/Pause key.'),
        ('next song / previous song', 'Triggers global media track keys.')
    ],
    'YouTube Music Controls': [
        ('open youtube music', 'Opens music.youtube.com.'),
        ('play music / pause music', 'Toggles playback on YouTube Music tab.'),
        ('next music / previous music', 'Skips tracks in YouTube Music.'),
        ('mute music / unmute music', 'Controls YouTube Music player volume.'),
        ('like this song / dislike this song', 'Rates the current track.'),
        ('shuffle music / shuffle on', 'Toggles shuffle.'),
        ('volume up music / volume down music', 'Adjusts YouTube Music volume.')
    ],
    'File Explorer Controls': [
        ('open first file / open second file', 'Opens the Nth file in the folder.'),
        ('select first file / next file / previous file', 'Navigates selection without opening.'),
        ('rename file', 'Triggers rename (F2).'),
        ('delete file', 'Deletes selected file.'),
        ('copy file / paste file / new folder', 'File management commands.')
    ],
    'Smart Dynamic Commands': [
        ('calculate [expression]', 'Evaluates spoken math (e.g. \'calculate fifteen times three\').'),
        ('search for [query]', 'Smart search (Google or YouTube Music based on context).'),
        ('google search for [query]', 'Forces a Google search.'),
        ('search in file explorer for [name]', 'Searches File Explorer.'),
        ('find file [filename]', 'Searches File Explorer for file.'),
        ('type [text]', 'Types text directly into the active cursor.'),
        ('open [app name] / close [app name]', 'Dynamic app launch/close.'),
        ('play [song/artist name]', 'Searches YouTube Music for the song.')
    ],
    'Gaze Tracker Voice Controls': [
        ('launch eye tracking / start eye cursor', 'Activates the MediaPipe camera gaze tracker.'),
        ('stop eye tracking / close eye cursor', 'Disables the camera gaze tracker.')
    ],
    'Settings & Assistant Controls': [
        ('open settings / show dashboard', 'Opens the NavTools Control Center GUI.'),
        ('close settings / hide panel', 'Closes the Control Center GUI.'),
        ('help / what can you do', 'Jim lists command categories vocally.'),
        ('stop listening / go to sleep', 'Sleep mode (ignores all speech until wake phrase).'),
        ('close the assistant / exit application', 'Completely shuts down NavTools.')
    ]
}

doc = SimpleDocTemplate(PDF_PATH, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=40, bottomMargin=30)
story = []

story.append(Paragraph('NavTools Voice Commands', title_style))
story.append(Paragraph('<b>Wake Phrase:</b> "wake up Jim" or "hey Jim"', normal_style))
story.append(Paragraph('Say the wake phrase before issuing any of the commands below.', note_style))
story.append(Spacer(1, 10))

for category, cmd_list in commands.items():
    story.append(Paragraph(category, h2_style))
    data = []
    for cmd, desc in cmd_list:
        data.append([
            Paragraph(f'<b>"{cmd}"</b>', normal_style),
            Paragraph(desc, normal_style)
        ])
    
    t = Table(data, colWidths=[200, 320])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), WHITE),
        ('TEXTCOLOR', (0, 0), (-1, -1), BLACK),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.lightgrey),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))

doc.build(story)
print(f'Created {PDF_PATH}')
