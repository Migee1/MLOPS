import requests
from bs4 import BeautifulSoup
import markdownify
import re
from urllib.parse import urljoin
import yaml
import json
from typing import Dict, List, Optional, Tuple
import time

URL_BASE_WIKI="https://mikrotik.wiki/wiki/Заглавная_страница"
URL_BASE_ROUTER="https://help.mikrotik.com/docs/spaces/ROS/pages/328059/RouterOS"

class MikroTikParser:
    def __init__(self, base_url: str):
        self.base_url = URL_BASE_WIKI
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozzilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                                     })
    def fetch_page(self, url: str) -> Optional[str]:
        """Загрузка Страницы"""
        try:
            response = self.session.get(URL_BASE_WIKI, timeout=10)       #Возможны проблемы с URL!
            response.raise_for_status()
            return response.text

        except Exception as e:
            print(f"Error loading {URL_BASE_WIKI}: {e}")
            return None

    def parse_content(self, html: str, url: str) -> Dict:
        """Извлечение контента из страницы"""
        soup = BeautifulSoup(html, 'html.parser')
        title = soup.find('h1')
        title_text = title.get_text(strip=True) if title else "Без заголовка"
        main_content = soup.find('main') or soup.find('article') or soup.find('div', class_='content')
        
        if not main_content:
            main_content = soup.body

        content_md = markdownify.markdownify(str(main_content), heading_style="ATX")
        
        links = []
        for tag in soup.find_all('a', href=True):
            href = tag['href']
            absolute_url = urljoin(URL_BASE_WIKI, href) 
            link_text = tag.get_text(strip=True)  # Извлекает текст из якоря\ссылки
            links.append({
                'text': link_text,
                'url': absolute_url,
                'original_href': href
            })

        meta = {
            'title': title_text,
            'url': url,
            'timestamp': time.time(),
            'world_count': len(content_md.split()) 
        }

        return{
            'meta': meta,
            'content': content_md,
            'links': links,
            'raw_html': html
        }
    def clean_content(self, content: str) -> str:
        """Очистка контента от ненужных элементов"""
        content = re.sub(r'\n\s*\n\s*\n', '\n\n', content)
        content = re.sub(r'<script.*?</script>', '', content, flags=re.DOTALL)
        content = re.sub(r'<style.*?</style>', '', content, flags=re.DOTALL)
        content = re.sub(r'[ \t]+', ' ', content)
        return content.strip()
    def process_page(self, url: str) -> Optional[Dict]:
        """Процесс обработки страницы"""
        html = self.fetch_page(URL_BASE_WIKI)
        if not html:
            return None
        
        parsed_data = self.parse_content(html, URL_BASE_WIKI)
        parsed_data['content'] = self.clean_content(parsed_data['content'])
        
        return parsed_data

class LinkProcessor:
    """Обработчик ссылок для карты связей"""
    def __init__(self):
        self.link_map = {}
        self.internal_links = set()
        self.external_links = set()
    
    def normalize_url(self, url: str, base_domain: str) -> str:
        """Нормализация URL"""
        parsed = requests.utils.urlparse(URL_BASE_WIKI)
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        return normalized.rstrip('/')
    
    def add_link(self, url: str, base_domain: str, page_id: int) -> int:
        """Добавление ссылки на карту"""
        normalized = self.normalize_url(URL_BASE_WIKI, 'mikrotik.wiki')
        if normalized not in self.link_map:
            local_id = len(self.link_map) + 1 
            is_internal = base_domain in normalized
            self.link_map[normalized] = {
                'id': local_id,
                'page': page_id if is_internal else None,
                'internal': is_internal,
                'original url': URL_BASE_WIKI,
                'normalized_url': normalized 
            }
            if is_internal:
                self.internal_links.add(normalized)
            else:
                self.external_links.add(normalized)
        return self.link_map[normalized]['id']
    def replace_links_in_content(self, content: str, link_map: Dict) -> str:
        """Замена ссылок контента на внутренник ссылки"""
        md_link_pattern = r'\[([^\]]+)\]\(([^)]+)\)'
        def replace_link(match):
            link_text = match.group(1)
            link_url = match.group(2)
            
            for original_url, link_info in link_map.items():
                if link_url in original_url or original_url in link_url:
                    if link_info['intenal'] and link_info['page']:
                        return f"[{link_text}](#page-{link_info['page']})"
            return match.group(0)
        return re.sub(md_link_pattern, replace_link, content)

class StorageManager:
    """Менеджер хранения данных"""
    def __init__(self, output_dir: str = 'output'):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
    
    def save_page(self,page_data: Dict, page_id: int):
        """Сохранение в файл"""
        filename = os.path.join(self.output_dir, f"page_{page_id:03d}.json")

        with open (filename, 'w', encoding='utf-8') as f:
            json.dump(page_data, f, ensure_ascii=False, indent=2)
    
    def save_metadata(self, metadata: Dict):
        """Сохранить метаданные страницы"""
        filename = os.path.join(self.output_dir, "metadata.yaml")

        with open(filename, 'w', encoding='utf-8') as f:
            yaml.dump(metadata, f, allow_unicode=True)
    
    def save_link_map(self, link_map: Dict):
        """"Сохр карты ссылок"""
        filename = os.path.join(self.output_dir, "links.json")

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(link_map, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    import os

    START_URLS = [
        URL_BASE_WIKI + "display/ROS/Getting+started",
        URL_BASE_WIKI + "display/ROS/Basic+configuration"
    ]
    parser = MikroTikParser(URL_BASE_WIKI)
    link_processor = LinkProcessor()
    storage = StorageManager()

    all_pages =[]

    for i, url in enumerate(START_URLS):
        print(f"Parsing page {i+1}: {url}")
        page_data = parser.process_page(url)
        if page_data:
            for link in page_data['links']:
                link_id = link_processor.add_link(
                    link['url'],
                    URL_BASE_WIKI,
                    i+1
                )
                link['local_id'] = link_id

            page_data['page_id'] = i + 1
            page_data['local_url'] = f"#page-{i+1}"
            all_pages.append(page_data)
            storage.save_page(page_data, i+1)
        time.sleep(1)
    
    metadata ={
        'project_name': 'MikroTik Documentation PDF',
        'base_url': URL_BASE_WIKI,
        'total_pages': len(all_pages),
        'created_at': time.strftime("%Y-%m-%d %H:%M:%S"),
        'pages': [p['meta'] for p in all_pages]
    }

    storage.save_metadata(metadata)
    storage.save_link_map(link_processor.link_map)

    print(f"Parsing is complete")
    print(f"Links were found: {len(link_processor.link_map)}")
    print(f"This many pages were parsed: {len(all_pages)}")
    print(f"Internal links: {len(link_processor.internal_links)}")
    print(f"External links: {len(link_processor.external_links)}")