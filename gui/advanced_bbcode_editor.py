# gui/advanced_bbcode_editor.py

"""
Advanced BBCode Editor with Live Preview
Integration for Process Threads - Forum Bot Application

Features:
- Advanced BBCode editor with syntax highlighting
- Live HTML preview of BBCode content
- Toolbar with common BBCode formatting buttons
- Split view between editor and preview
- Real-time conversion and preview updates
- Integrated within existing Process Threads UI
"""

import logging
import re
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QToolBar, 
    QAction, QSplitter, QLabel, QTextBrowser, QPushButton,
    QColorDialog, QInputDialog, QMessageBox, QComboBox,
    QSpinBox, QGroupBox, QTabWidget, QApplication
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import (
    QFont, QTextCharFormat, QSyntaxHighlighter, QTextDocument, 
    QColor, QIcon, QKeySequence, QTextCursor
)


class BBCodeSyntaxHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for BBCode tags"""
    
    def __init__(self, document):
        super().__init__(document)
        self.setup_highlighting_rules()
    
    def setup_highlighting_rules(self):
        """Setup syntax highlighting rules for BBCode"""
        self.highlighting_rules = []
        
        # BBCode tag format
        bbcode_format = QTextCharFormat()
        bbcode_format.setForeground(QColor(34, 139, 34))  # Forest Green
        bbcode_format.setFontWeight(QFont.Bold)
        
        # Match opening and closing BBCode tags
        bbcode_pattern = r'\[/?[a-zA-Z0-9=\s#]*\]'
        self.highlighting_rules.append((bbcode_pattern, bbcode_format))
        
        # URL format
        url_format = QTextCharFormat()
        url_format.setForeground(QColor(0, 0, 255))  # Blue
        url_format.setFontUnderline(True)
        url_pattern = r'https?://[^\s\[\]]+'
        self.highlighting_rules.append((url_pattern, url_format))
        
        # Quote content format
        quote_format = QTextCharFormat()
        quote_format.setForeground(QColor(105, 105, 105))  # Dim Gray
        quote_format.setFontItalic(True)
        
    def highlightBlock(self, text):
        """Apply syntax highlighting to text block"""
        for pattern, format_obj in self.highlighting_rules:
            expression = re.compile(pattern)
            for match in expression.finditer(text):
                start = match.start()
                length = match.end() - start
                self.setFormat(start, length, format_obj)


class BBCodeConverter:
    """Convert BBCode to HTML for preview"""
    
    @staticmethod
    def bbcode_to_html(bbcode_text):
        """Convert BBCode to HTML"""
        html = bbcode_text
        
        # Basic formatting
        html = re.sub(r'\[b\](.*?)\[/b\]', r'<strong>\1</strong>', html, flags=re.IGNORECASE | re.DOTALL)
        html = re.sub(r'\[i\](.*?)\[/i\]', r'<em>\1</em>', html, flags=re.IGNORECASE | re.DOTALL)
        html = re.sub(r'\[u\](.*?)\[/u\]', r'<u>\1</u>', html, flags=re.IGNORECASE | re.DOTALL)
        html = re.sub(r'\[s\](.*?)\[/s\]', r'<s>\1</s>', html, flags=re.IGNORECASE | re.DOTALL)
        
        # Colors
        html = re.sub(r'\[color=([^\]]+)\](.*?)\[/color\]', r'<span style="color: \1">\2</span>', html, flags=re.IGNORECASE | re.DOTALL)
        
        # Size
        html = re.sub(r'\[size=(\d+)\](.*?)\[/size\]', r'<span style="font-size: \1px">\2</span>', html, flags=re.IGNORECASE | re.DOTALL)
        
        # Font
        html = re.sub(r'\[font=([^\]]+)\](.*?)\[/font\]', r'<span style="font-family: \1">\2</span>', html, flags=re.IGNORECASE | re.DOTALL)
        
        # Links
        html = re.sub(r'\[url=([^\]]+)\](.*?)\[/url\]', r'<a href="\1" target="_blank">\2</a>', html, flags=re.IGNORECASE | re.DOTALL)
        html = re.sub(r'\[url\](.*?)\[/url\]', r'<a href="\1" target="_blank">\1</a>', html, flags=re.IGNORECASE | re.DOTALL)
        
        # Images
        html = re.sub(r'\[img\](.*?)\[/img\]', r'<img src="\1" style="max-width: 100%; height: auto;" />', html, flags=re.IGNORECASE | re.DOTALL)
        html = re.sub(r'\[img=(\d+)x(\d+)\](.*?)\[/img\]', r'<img src="\3" width="\1" height="\2" />', html, flags=re.IGNORECASE | re.DOTALL)
        
        # Quotes
        html = re.sub(r'\[quote\](.*?)\[/quote\]', r'<blockquote style="border-left: 3px solid #ccc; padding-left: 10px; margin: 10px 0; font-style: italic;">\1</blockquote>', html, flags=re.IGNORECASE | re.DOTALL)
        html = re.sub(r'\[quote=([^\]]+)\](.*?)\[/quote\]', r'<blockquote style="border-left: 3px solid #ccc; padding-left: 10px; margin: 10px 0;"><strong>\1 said:</strong><br>\2</blockquote>', html, flags=re.IGNORECASE | re.DOTALL)
        
        # Code blocks
        html = re.sub(r'\[code\](.*?)\[/code\]', r'<pre style="background-color: #f4f4f4; padding: 10px; border: 1px solid #ddd; font-family: monospace;">\1</pre>', html, flags=re.IGNORECASE | re.DOTALL)
        
        # Lists
        html = re.sub(r'\[list\](.*?)\[/list\]', r'<ul>\1</ul>', html, flags=re.IGNORECASE | re.DOTALL)
        html = re.sub(r'\[list=1\](.*?)\[/list\]', r'<ol>\1</ol>', html, flags=re.IGNORECASE | re.DOTALL)
        html = re.sub(r'\[\*\](.*?)(?=\[\*\]|\[/list\])', r'<li>\1</li>', html, flags=re.IGNORECASE | re.DOTALL)
        
        # Spoilers
        html = re.sub(r'\[spoiler\](.*?)\[/spoiler\]', r'<details style="border: 1px solid #ddd; padding: 5px; margin: 5px 0;"><summary style="cursor: pointer; font-weight: bold;">Spoiler</summary>\1</details>', html, flags=re.IGNORECASE | re.DOTALL)
        html = re.sub(r'\[spoiler=([^\]]+)\](.*?)\[/spoiler\]', r'<details style="border: 1px solid #ddd; padding: 5px; margin: 5px 0;"><summary style="cursor: pointer; font-weight: bold;">\1</summary>\2</details>', html, flags=re.IGNORECASE | re.DOTALL)
        
        # Center and alignment
        html = re.sub(r'\[center\](.*?)\[/center\]', r'<div style="text-align: center;">\1</div>', html, flags=re.IGNORECASE | re.DOTALL)
        html = re.sub(r'\[left\](.*?)\[/left\]', r'<div style="text-align: left;">\1</div>', html, flags=re.IGNORECASE | re.DOTALL)
        html = re.sub(r'\[right\](.*?)\[/right\]', r'<div style="text-align: right;">\1</div>', html, flags=re.IGNORECASE | re.DOTALL)
        
        # Line breaks
        html = html.replace('\n', '<br>')
        
        return html


class AdvancedBBCodeEditor(QWidget):
    """Advanced BBCode Editor with Live Preview"""
    
    # Signal emitted when content changes
    content_changed = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.setup_connections()
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_preview)
        self.update_timer.setSingleShot(True)
        
    def setup_ui(self):
        """Setup the user interface"""
        main_layout = QVBoxLayout(self)
        
        # Create toolbar
        self.create_toolbar()
        main_layout.addWidget(self.toolbar)
        
        # Create main content area with splitter
        self.main_splitter = QSplitter(Qt.Horizontal)
        
        # Left side: Editor
        self.create_editor_panel()
        
        # Right side: Preview
        self.create_preview_panel()
        
        # Add panels to splitter
        self.main_splitter.addWidget(self.editor_group)
        self.main_splitter.addWidget(self.preview_group)
        
        # Set equal sizes for both panels
        self.main_splitter.setSizes([400, 400])
        
        main_layout.addWidget(self.main_splitter)
        
    def create_toolbar(self):
        """Create formatting toolbar"""
        self.toolbar = QToolBar("BBCode Formatting")
        self.toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        
        # Bold
        bold_action = QAction("B", self)
        bold_action.setToolTip("Bold [b]text[/b]")
        bold_action.setShortcut(QKeySequence.Bold)
        bold_action.triggered.connect(lambda: self.apply_formatting("b"))
        self.toolbar.addAction(bold_action)
        
        # Italic
        italic_action = QAction("I", self)
        italic_action.setToolTip("Italic [i]text[/i]")
        italic_action.setShortcut(QKeySequence.Italic)
        italic_action.triggered.connect(lambda: self.apply_formatting("i"))
        self.toolbar.addAction(italic_action)
        
        # Underline
        underline_action = QAction("U", self)
        underline_action.setToolTip("Underline [u]text[/u]")
        underline_action.setShortcut(QKeySequence.Underline)
        underline_action.triggered.connect(lambda: self.apply_formatting("u"))
        self.toolbar.addAction(underline_action)
        
        # Strikethrough
        strike_action = QAction("S", self)
        strike_action.setToolTip("Strikethrough [s]text[/s]")
        strike_action.triggered.connect(lambda: self.apply_formatting("s"))
        self.toolbar.addAction(strike_action)
        
        self.toolbar.addSeparator()
        
        # Color
        color_action = QAction("Color", self)
        color_action.setToolTip("Text Color")
        color_action.triggered.connect(self.apply_color)
        self.toolbar.addAction(color_action)
        
        # Font size
        self.size_combo = QComboBox()
        self.size_combo.addItems(["8", "10", "12", "14", "16", "18", "20", "24", "28", "32"])
        self.size_combo.setCurrentText("12")
        self.size_combo.setToolTip("Font Size")
        self.size_combo.currentTextChanged.connect(self.apply_size)
        self.toolbar.addWidget(QLabel("Size:"))
        self.toolbar.addWidget(self.size_combo)
        
        self.toolbar.addSeparator()
        
        # URL
        url_action = QAction("URL", self)
        url_action.setToolTip("Insert Link [url]")
        url_action.triggered.connect(self.insert_url)
        self.toolbar.addAction(url_action)
        
        # Image
        img_action = QAction("IMG", self)
        img_action.setToolTip("Insert Image [img]")
        img_action.triggered.connect(self.insert_image)
        self.toolbar.addAction(img_action)
        
        # Quote
        quote_action = QAction("Quote", self)
        quote_action.setToolTip("Quote [quote]")
        quote_action.triggered.connect(self.insert_quote)
        self.toolbar.addAction(quote_action)
        
        # Code
        code_action = QAction("Code", self)
        code_action.setToolTip("Code Block [code]")
        code_action.triggered.connect(lambda: self.apply_formatting("code"))
        self.toolbar.addAction(code_action)
        
        self.toolbar.addSeparator()
        
        # List
        list_action = QAction("List", self)
        list_action.setToolTip("Bulleted List")
        list_action.triggered.connect(self.insert_list)
        self.toolbar.addAction(list_action)
        
        # Spoiler
        spoiler_action = QAction("Spoiler", self)
        spoiler_action.setToolTip("Spoiler Tag")
        spoiler_action.triggered.connect(self.insert_spoiler)
        self.toolbar.addAction(spoiler_action)
        
    def create_editor_panel(self):
        """Create the BBCode editor panel"""
        self.editor_group = QGroupBox("BBCode Editor")
        editor_layout = QVBoxLayout(self.editor_group)
        
        # Create text editor
        self.editor = QTextEdit()
        self.editor.setFont(QFont("Consolas", 11))
        self.editor.setAcceptRichText(False)  # Plain text only
        self.editor.setTabStopWidth(40)
        
        # Apply syntax highlighting
        self.highlighter = BBCodeSyntaxHighlighter(self.editor.document())
        
        editor_layout.addWidget(self.editor)
        
    def create_preview_panel(self):
        """Create the HTML preview panel"""
        self.preview_group = QGroupBox("Live Preview")
        preview_layout = QVBoxLayout(self.preview_group)
        
        # Create preview browser
        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(True)
        
        # Add refresh button
        refresh_btn = QPushButton("🔄 Refresh Preview")
        refresh_btn.clicked.connect(self.update_preview)
        
        preview_layout.addWidget(refresh_btn)
        preview_layout.addWidget(self.preview)
        
    def setup_connections(self):
        """Setup signal connections"""
        self.editor.textChanged.connect(self.on_text_changed)
        
    def on_text_changed(self):
        """Handle text changes in editor"""
        # Delay update to avoid too frequent updates
        self.update_timer.stop()
        self.update_timer.start(500)  # 500ms delay
        
        # Emit content changed signal
        self.content_changed.emit(self.get_text())
        
    def update_preview(self):
        """Update the HTML preview"""
        try:
            bbcode_text = self.editor.toPlainText()
            html_content = BBCodeConverter.bbcode_to_html(bbcode_text)
            
            # Wrap in proper HTML structure
            full_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <style>
                    body {{ 
                        font-family: Arial, sans-serif; 
                        line-height: 1.6; 
                        margin: 10px; 
                        background-color: white;
                    }}
                    blockquote {{ 
                        background-color: #f9f9f9; 
                        padding: 10px;
                        margin: 10px 0;
                    }}
                    pre {{ 
                        background-color: #f4f4f4; 
                        padding: 10px; 
                        overflow-x: auto;
                    }}
                    img {{ 
                        max-width: 100%; 
                        height: auto; 
                    }}
                </style>
            </head>
            <body>
                {html_content}
            </body>
            </html>
            """
            
            self.preview.setHtml(full_html)
            
        except Exception as e:
            logging.error(f"Error updating BBCode preview: {e}")
            self.preview.setHtml(f"<p style='color: red;'>Preview Error: {str(e)}</p>")
    
    def apply_formatting(self, tag):
        """Apply BBCode formatting to selected text"""
        cursor = self.editor.textCursor()
        selected_text = cursor.selectedText()
        
        if selected_text:
            formatted_text = f"[{tag}]{selected_text}[/{tag}]"
            cursor.insertText(formatted_text)
        else:
            # Insert empty tags and position cursor between them
            cursor.insertText(f"[{tag}][/{tag}]")
            # Move cursor back to position between tags
            position = cursor.position() - len(f"[/{tag}]")
            cursor.setPosition(position)
            self.editor.setTextCursor(cursor)
        
        self.editor.setFocus()
    
    def apply_color(self):
        """Apply color formatting"""
        color = QColorDialog.getColor(Qt.black, self, "Select Text Color")
        if color.isValid():
            cursor = self.editor.textCursor()
            selected_text = cursor.selectedText()
            color_name = color.name()
            
            if selected_text:
                formatted_text = f"[color={color_name}]{selected_text}[/color]"
                cursor.insertText(formatted_text)
            else:
                cursor.insertText(f"[color={color_name}][/color]")
                position = cursor.position() - 8  # Position before [/color]
                cursor.setPosition(position)
                self.editor.setTextCursor(cursor)
        
        self.editor.setFocus()
    
    def apply_size(self, size):
        """Apply font size formatting"""
        cursor = self.editor.textCursor()
        selected_text = cursor.selectedText()
        
        if selected_text:
            formatted_text = f"[size={size}]{selected_text}[/size]"
            cursor.insertText(formatted_text)
        else:
            cursor.insertText(f"[size={size}][/size]")
            position = cursor.position() - 7  # Position before [/size]
            cursor.setPosition(position)
            self.editor.setTextCursor(cursor)
        
        self.editor.setFocus()
    
    def insert_url(self):
        """Insert URL tag"""
        url, ok = QInputDialog.getText(self, "Insert URL", "Enter URL:")
        if ok and url:
            text, ok2 = QInputDialog.getText(self, "Link Text", "Enter link text (optional):")
            cursor = self.editor.textCursor()
            
            if ok2 and text:
                cursor.insertText(f"[url={url}]{text}[/url]")
            else:
                cursor.insertText(f"[url]{url}[/url]")
        
        self.editor.setFocus()
    
    def insert_image(self):
        """Insert image tag"""
        url, ok = QInputDialog.getText(self, "Insert Image", "Enter image URL:")
        if ok and url:
            cursor = self.editor.textCursor()
            cursor.insertText(f"[img]{url}[/img]")
        
        self.editor.setFocus()
    
    def insert_quote(self):
        """Insert quote tag"""
        author, ok = QInputDialog.getText(self, "Quote", "Enter author (optional):")
        cursor = self.editor.textCursor()
        
        if ok and author:
            cursor.insertText(f"[quote={author}][/quote]")
            position = cursor.position() - 8  # Position before [/quote]
        else:
            cursor.insertText("[quote][/quote]")
            position = cursor.position() - 8  # Position before [/quote]
        
        cursor.setPosition(position)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()
    
    def insert_list(self):
        """Insert list tags"""
        cursor = self.editor.textCursor()
        list_content = "[list]\n[*]Item 1\n[*]Item 2\n[*]Item 3\n[/list]"
        cursor.insertText(list_content)
        self.editor.setFocus()
    
    def insert_spoiler(self):
        """Insert spoiler tag"""
        title, ok = QInputDialog.getText(self, "Spoiler", "Enter spoiler title (optional):")
        cursor = self.editor.textCursor()
        
        if ok and title:
            cursor.insertText(f"[spoiler={title}][/spoiler]")
            position = cursor.position() - 10  # Position before [/spoiler]
        else:
            cursor.insertText("[spoiler][/spoiler]")
            position = cursor.position() - 10  # Position before [/spoiler]
        
        cursor.setPosition(position)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()
    
    def get_text(self):
        """Get the BBCode text from editor"""
        return self.editor.toPlainText()
    
    def set_text(self, text):
        """Set text in the editor"""
        self.editor.setPlainText(text)
        self.update_preview()
    
    def clear(self):
        """Clear the editor and preview"""
        self.editor.clear()
        self.preview.clear()
    
    def insert_text(self, text):
        """Insert text at cursor position"""
        cursor = self.editor.textCursor()
        cursor.insertText(text)
        self.editor.setFocus()
