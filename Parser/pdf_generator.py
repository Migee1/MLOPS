from fpdf import FPDF
import json
import os
import markdown
from html.parser import HTMLParser

class HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs= True
        self.text = []
    
    def handle_data(self, d):
        self.text.append(d)
    
    def get_data(self):
        return ''.join(self.text)

class SimplePDFGenerator:
    def __init__(self, output_dir='output'):
        self.output_dir = output_dir
        self.pdf = FPDF()
        self.pdf.add_page()
        self.pdf.add_font('DejaVu', '', 'DejaVuSans.ttf', uni=True)
        self.pdf.set_font('DejaVu', '', 12)
    
    def strip_html(self, html):
        """Удаление HTML-тегов"""
        s = HTMLStripper()
        s.feed(html)
        return s.get_data()
    
    def load_and_generate(self, filename='mikrotik_docs.pdf'):
        pages = []
        
        # Загрузка страниц
        for fname in sorted(os.listdir(self.output_dir)):
            if fname.startswith('page_') and fname.endswith('.json'):
                with open(os.path.join(self.output_dir, fname), 'r', encoding='utf-8') as f:
                    pages.append(json.load(f))
        
        if not pages:
            print("Нет данных!")
            return
        
        # Генерация PDF
        self.pdf.set_auto_page_break(auto=True, margin=15)
        
        # Оглавление
        self.pdf.set_font('DejaVu', 'B', 16)
        self.pdf.cell(0, 10, 'MikroTik Documentation', 0, 1, 'C')
        self.pdf.ln(10)
        
        self.pdf.set_font('DejaVu', 'B', 14)
        self.pdf.cell(0, 10, 'Table of Contents', 0, 1)
        self.pdf.ln(5)
        
        for i, page in enumerate(pages):
            self.pdf.set_font('DejaVu', '', 12)
            title = page['meta']['title'][:100]  # Ограничиваем длину
            self.pdf.cell(0, 8, f"{i+1}. {title}", 0, 1)
        
        self.pdf.add_page()
        
        # Контент страниц
        for i, page in enumerate(pages):
            self.pdf.set_font('DejaVu', 'B', 16)
            self.pdf.cell(0, 10, f"{i+1}. {page['meta']['title']}", 0, 1)
            self.pdf.ln(5)
            
            # Конвертируем Markdown в текст (упрощенно)
            content = page['content']
            
            # Разбиваем на строки
            lines = content.split('\n')
            
            self.pdf.set_font('DejaVu', '', 12)
            for line in lines:
                if line.strip().startswith('#'):
                    # Заголовки
                    level = len(line) - len(line.lstrip('#'))
                    font_size = 16 - (level * 2)
                    self.pdf.set_font('DejaVu', 'B', font_size)
                    self.pdf.cell(0, 8, line.lstrip('#').strip(), 0, 1)
                    self.pdf.set_font('DejaVu', '', 12)
                else:
                    # Обычный текст
                    if len(line) > 80:
                        # Перенос длинных строк
                        self.pdf.multi_cell(0, 6, line)
                    else:
                        self.pdf.cell(0, 6, line, 0, 1)
            
            if i < len(pages) - 1:
                self.pdf.add_page()
        
        # Сохранение
        pdf_path = os.path.join(self.output_dir, filename)
        self.pdf.output(pdf_path)
        print(f"✅ PDF создан: {pdf_path}")

# Быстрый запуск
if __name__ == "__main__":
    generator = SimplePDFGenerator()
    generator.load_and_generate()