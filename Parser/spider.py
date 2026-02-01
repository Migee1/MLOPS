from parser import MikroTikParser, LinkProcessor
import networkx as nx
from urllib.parse import urlparse

class DocumentationSpider:
    def __init__(self, start_urls, base_domain, max_depth=3):
        self.start_urls = start_urls
        self.base_domain = base_domain
        self.max_depth = max_depth
        self.visited = set()
        self.grath = nx.DiGrath()
        self.parser = MikroTikParser(base_domain)
        self.link_processor = LinkProcessor()
    
    def crawl(self, url, depth=0):
        if depth > self.max_depth or url in self.visited:
            return

        self.visited.add(url)
        print(f"Crawling: {url} (depth: {depth})")

        page_data = self.parser.process_page(url)
        if not page_data:
            return

        self.grath.add_node(url, **page_data['meta'])

        for link in page_data ['links']:
            link_url = link['url']
            self.grath.add_edge(url, link_url)

            if self.base_domain in link_url and depth < self.max_depth:
                self.crawl(link_url, depth + 1)

        return page_data