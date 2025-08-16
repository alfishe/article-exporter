import os
import re
import requests
from urllib.parse import urljoin, urlparse
from typing import Optional, List, Tuple
from bs4 import BeautifulSoup, NavigableString, Tag
from datetime import datetime
import argparse
import sys


# Simple Article class for standalone usage
class Article:
    def __init__(self, url: str, title: str = None, author: str = None, published_date: str = None):
        self.url = url
        self.title = title
        self.author = author
        self.published_date = published_date

    @classmethod
    def from_url(cls, url: str):
        """Create an Article instance from just a URL"""
        return cls(url=url, title=None, author=None, published_date=None)

# Remove external dependencies for standalone usage
# from .database import Article
# from .url_normalizer import normalize_url


class ArticleExporter:
    """Export articles as cleaned Markdown with local images.

    This exporter fetches original HTML by URL, extracts the main content,
    removes layout/ads/external links, downloads content images, and writes
    Markdown into a unique folder per article under /articles.
    """

    def __init__(self, output_root: str = "./articles", request_timeout: int = 30, request_delay: float = 0.5, 
                 no_images: bool = False, verbose: bool = False):
        self.output_root = output_root
        self.request_timeout = request_timeout
        self.request_delay = request_delay
        self.no_images = no_images
        self.verbose = verbose
        os.makedirs(self.output_root, exist_ok=True)
        # Simple headers to mimic a browser
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.8',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }

    def export_article(self, article: Article) -> str:
        """Export a single article to a unique folder and return the folder path."""
        if not article or not article.url:
            raise ValueError("Article with URL is required for export")

        # Ensure URL has scheme for fetching
        fetch_url = article.url
        if fetch_url and not fetch_url.startswith(('http://', 'https://')):
            fetch_url = 'https://' + fetch_url

        html = self._fetch_html(fetch_url)
        if not html:
            raise RuntimeError(f"Failed to fetch article HTML: {fetch_url}")

        soup = BeautifulSoup(html, 'html.parser')
        
        # Extract title and author from the HTML
        if not article.title:
            article.title = self._extract_title(soup)
        if not article.author:
            article.author = self._extract_author(soup)
        
        content_root = self._extract_main_content(soup)
        if content_root is None:
            # Fallback to body
            content_root = soup.find('body') or soup

        # Remove unwanted elements (ads, nav, comments, etc.)
        self._remove_unwanted_elements(content_root)

        # Prepare destination folder and filenames
        folder_path = self._create_unique_article_folder(article)
        if self.verbose:
            print(f"Export folder: {folder_path}")

        # Build Markdown while in-order downloading images and replacing with local refs
        base_url = fetch_url
        if self.verbose:
            print("Converting HTML to Markdown...")
        markdown = self._element_to_markdown(content_root, base_url, folder_path)

        # Compose final Markdown content with basic frontmatter
        md_lines = []
        md_lines.append(f"# {article.title.strip() if article.title else 'Untitled'}")
        meta_parts = []
        if article.author:
            meta_parts.append(f"Author: {article.author}")
        if article.published_date:
            meta_parts.append(f"Published: {article.published_date.strftime('%Y-%m-%d %H:%M')}")
        if fetch_url:
            display_url = fetch_url
            meta_parts.append(f"Original URL: [{display_url}]({fetch_url})")
        if meta_parts:
            md_lines.append('')
            for m in meta_parts:
                md_lines.append(f"- {m}")
            # Delimiter after metadata block
            md_lines.append('')
            md_lines.append('---')
        md_lines.append('')
        
        md_lines.append(markdown.strip())
        md_content = "\n".join(md_lines).strip() + "\n"

        # Final cleanup: remove bracket-only garbage lines and collapse excessive blanks
        md_content = self._cleanup_markdown(md_content) + "\n"

        # Save Markdown file
        markdown_path = os.path.join(folder_path, 'article.md')
        with open(markdown_path, 'w', encoding='utf-8') as f:
            f.write(md_content)
        
        if self.verbose:
            print(f"Markdown saved to: {markdown_path}")

        return folder_path

    def _fetch_html(self, url: str) -> Optional[str]:
        import time
        if self.verbose:
            print(f"Fetching HTML from: {url}")
        time.sleep(self.request_delay)
        resp = requests.get(url, headers=self.headers, timeout=self.request_timeout, allow_redirects=True)
        resp.raise_for_status()
        ctype = resp.headers.get('content-type', '').lower()
        if 'text/html' not in ctype:
            if self.verbose:
                print(f"  → Content type not HTML: {ctype}")
            return None
        if self.verbose:
            print(f"  → Successfully fetched {len(resp.text)} characters")
        return resp.text

    def _extract_title(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract article title from various HTML elements."""
        # Try common title selectors
        title_selectors = [
            'h1',
            '.article-title', '.post-title', '.entry-title', '.title',
            '[property="og:title"]', '[name="twitter:title"]',
            'title'  # fallback to page title
        ]
        
        for selector in title_selectors:
            el = soup.select_one(selector)
            if el:
                title = el.get_text(strip=True)
                if title and len(title) > 5:  # Avoid very short titles
                    return title
        
        return None

    def _extract_author(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract article author from various HTML elements."""
        # Try common author selectors
        author_selectors = [
            '.post-author-name', '.author-name', '.byline', '.author', '.post-author', '.entry-author',
            '[rel="author"]', '[property="author"]', '[name="author"]',
            '[class*="author"]', '[class*="byline"]'
        ]
        
        for selector in author_selectors:
            el = soup.select_one(selector)
            if el:
                author = el.get_text(strip=True)
                if author and len(author) > 2:  # Avoid very short author names
                    # Clean up common prefixes
                    author = re.sub(r'^(by|By|BY)\s+', '', author)
                    author = re.sub(r'^\s*[-–—]\s*', '', author)
                    if author and len(author) > 2:
                        return author
        
        return None

    def _extract_main_content(self, soup: BeautifulSoup) -> Optional[Tag]:
        # Prefer common article/content containers
        selectors = [
            'article',
            '.article-content', '.post-content', '.entry-content', '.content',
            '.article-body', '.post-body', '.entry-body', '.article-text', '.post-text', '.entry-text',
            'main', '[role="main"]', '#main', '#content', '.main'
        ]
        for selector in selectors:
            el = soup.select_one(selector)
            if el and self._text_length(el) > 200:
                return el
        # Heuristic: find the div with most text
        best = None
        best_len = 0
        for div in soup.find_all(['div', 'section']):
            ln = self._text_length(div)
            if ln > best_len:
                best_len = ln
                best = div
        return best

    def _text_length(self, el: Tag) -> int:
        txt = re.sub(r'\s+', ' ', el.get_text(strip=True))
        return len(txt)

    def _remove_unwanted_elements(self, root: Tag) -> None:
        unwanted_selectors = [
            'nav', 'header', 'footer', 'aside',
            '.nav', '.navigation', '.menu', '.sidebar',
            '.ad', '.advertisement', '.ads', '[class*="ad"]',
            '.social', '.share', '.comments', '[class*="social"]', '[class*="share"]', '[class*="comment"]',
            '.related', '.recommended',
            'script', 'style', 'noscript', 'iframe', 'form'
        ]
        for sel in unwanted_selectors:
            for n in root.select(sel):
                n.decompose()



    def _safe_folder_name(self, text: str, max_length: int = 32) -> str:
        """Create a filesystem-safe folder name while preserving UTF-8 characters"""
        if not text:
            return 'untitled'
        
        # Remove or replace problematic filesystem characters
        # Keep alphanumeric, spaces, and most UTF-8 characters
        # Replace problematic characters with safe alternatives
        safe_text = text.strip()
        
        # Replace problematic filesystem characters
        replacements = {
            '<': '(', '>': ')', '|': '-', ':': '-', '"': "'", '*': 'x',
            '?': '', '\\': '-', '/': '-', '\0': '', '\t': ' ', '\n': ' ',
            '\r': ' ', '\f': ' ', '\v': ' '
        }
        
        for old, new in replacements.items():
            safe_text = safe_text.replace(old, new)
        
        # Remove any remaining control characters
        safe_text = ''.join(char for char in safe_text if ord(char) >= 32)
        
        # Normalize whitespace
        safe_text = re.sub(r'\s+', ' ', safe_text)
        
        # Trim to max length, trying to break at word boundaries
        if len(safe_text) > max_length:
            # Try to break at word boundary
            words = safe_text.split()
            result = ''
            for word in words:
                if len(result + ' ' + word) <= max_length:
                    result = (result + ' ' + word).strip()
                else:
                    break
            safe_text = result or safe_text[:max_length]
        
        return safe_text.strip() or 'untitled'

    def _create_unique_article_folder(self, article: Article) -> str:
        # Format: <exportdate>-<url-hash>-<Title trimmed to 32 symbols>
        export_date = datetime.now().strftime('%Y%m%d')
        id_part = self._fallback_id_from_url(article.url)
        
        # Clean and trim title to 32 symbols while preserving UTF-8
        title_part = self._safe_folder_name(article.title, 32) if article.title else 'untitled'
        
        base = f"{export_date}-{id_part}-{title_part}"
        folder = os.path.join(self.output_root, base)
        
        suffix = 1
        while os.path.exists(folder):
            folder_try = f"{folder}-{suffix}"
            if not os.path.exists(folder_try):
                folder = folder_try
                break
            suffix += 1
        
        os.makedirs(folder, exist_ok=True)
        return folder

    def _fallback_id_from_url(self, url: str) -> str:
        try:
            parsed = urlparse(url)
            raw = (parsed.path or '').strip('/').replace('/', '-')
            raw = raw or parsed.netloc
            return re.sub(r'[^a-zA-Z0-9\-]', '', raw)[:40] or 'u'
        except Exception:
            return 'u'

    def _detect_code_language(self, pre_tag: Tag, code_tag: Optional[Tag]) -> Optional[str]:
        """Try to detect code language from class names and data attributes."""
        candidates: List[str] = []

        def collect_from(tag: Optional[Tag]) -> None:
            if not tag:
                return
            # class tokens
            for cls in tag.get('class', []):
                candidates.append(str(cls).lower())
            # common attributes
            for attr in ['data-lang', 'data-language', 'lang', 'language']:
                val = tag.get(attr)
                if val:
                    candidates.append(str(val).lower())

        collect_from(pre_tag)
        collect_from(code_tag)

        # Normalize and map aliases
        alias_map = {
            'js': 'javascript', 'jsx': 'jsx', 'javascript': 'javascript',
            'ts': 'typescript', 'tsx': 'tsx', 'typescript': 'typescript',
            'py': 'python', 'python': 'python',
            'rb': 'ruby', 'ruby': 'ruby',
            'php': 'php',
            'java': 'java', 'kotlin': 'kotlin', 'swift': 'swift',
            'c': 'c', 'cpp': 'cpp', 'c++': 'cpp', 'cc': 'cpp', 'hpp': 'cpp',
            'cs': 'csharp', 'c#': 'csharp', 'csharp': 'csharp',
            'go': 'go', 'golang': 'go',
            'rs': 'rust', 'rust': 'rust',
            'sh': 'bash', 'bash': 'bash', 'zsh': 'bash', 'shell': 'bash', 'console': 'bash',
            'yaml': 'yaml', 'yml': 'yaml', 'json': 'json', 'toml': 'toml', 'ini': 'ini',
            'html': 'html', 'xml': 'xml', 'css': 'css', 'scss': 'scss', 'less': 'less',
            'sql': 'sql', 'graphql': 'graphql', 'proto': 'protobuf', 'protobuf': 'protobuf',
            'dockerfile': 'dockerfile', 'docker': 'dockerfile',
            'make': 'makefile', 'makefile': 'makefile', 'cmake': 'cmake',
            'gradle': 'gradle', 'groovy': 'groovy',
            'lua': 'lua', 'r': 'r', 'matlab': 'matlab', 'perl': 'perl', 'ps': 'powershell', 'ps1': 'powershell', 'powershell': 'powershell',
            'hcl': 'hcl', 'terraform': 'hcl'
        }

        for token in candidates:
            if token == 'hljs':
                continue
            # language-xxx or lang-xxx
            m = re.match(r'^(?:language|lang)[-_]([a-z0-9+#]+)$', token)
            if m:
                key = m.group(1)
                return alias_map.get(key, key)
            # direct alias
            norm = token.strip('.#')
            if norm in alias_map:
                return alias_map[norm]

        return None

    def _fence_code_block(self, code_text: str, language: Optional[str]) -> List[str]:
        """Return fenced code block lines with dynamic fence length and optional language."""
        code_text = code_text.rstrip('\n')
        longest_backticks = 0
        for m in re.finditer(r'`+', code_text):
            longest_backticks = max(longest_backticks, len(m.group(0)))
        fence = '`' * max(3, longest_backticks + 1)
        opening = fence if not language else f"{fence}{language}"
        return [opening, code_text, fence, ""]

    def _inline_code_span(self, text: str) -> str:
        """Return inline code span using backticks with safe delimiter length."""
        longest_backticks = 0
        for m in re.finditer(r'`+', text):
            longest_backticks = max(longest_backticks, len(m.group(0)))
        fence = '`' * max(1, longest_backticks + 1)
        return f"{fence}{text}{fence}"

    def _element_to_markdown(self, el: Tag, base_url: str, article_folder: str) -> str:
        lines: List[str] = []

        def walk(node) -> List[str]:
            if isinstance(node, NavigableString):
                return [self._escape_md(str(node))]
            if not isinstance(node, Tag):
                return []

            name = node.name.lower()
            if name in ['script', 'style', 'noscript', 'iframe', 'form']:
                return []

            if name in ['h1','h2','h3','h4','h5','h6']:
                level = int(name[1])
                text = self._collect_inline_text(node)
                return [f"{'#'*level} {text}", ""]

            if name in ['p']:
                content = self._collect_inline(node, base_url, article_folder)
                return [content, ""] if content.strip() else []

            if name in ['ul', 'ol']:
                buf: List[str] = []
                is_ol = (name == 'ol')
                idx = 1
                for li in node.find_all('li', recursive=False):
                    li_md = self._collect_inline(li, base_url, article_folder)
                    prefix = f"{idx}. " if is_ol else "- "
                    buf.append(prefix + li_md)
                    idx += 1
                buf.append("")
                return buf

            if name == 'pre':
                # Code block with language detection and safe fencing
                code_tag = node.find('code')
                # Preserve inner text as-is (including newlines/indentation)
                code_text = code_tag.get_text() if code_tag else node.get_text()
                language = self._detect_code_language(node, code_tag)
                return self._fence_code_block(code_text, language)

            if name == 'blockquote':
                inner = self._collect_inline(node, base_url, article_folder)
                quoted = ["> " + ln if ln else ">" for ln in inner.split('\n')]
                return quoted + [""]

            # Default: recurse children inline
            return self._collect_children(node, base_url, article_folder)

        for child in el.children:
            lines.extend(walk(child))

        # Normalize extra blank lines
        joined = "\n".join(lines)
        joined = re.sub(r"\n{3,}", "\n\n", joined)
        return joined.strip()

    def _cleanup_markdown(self, content: str) -> str:
        """Remove stray bracket-only lines and normalize spacing."""
        lines = content.splitlines()
        cleaned: List[str] = []
        for ln in lines:
            # Drop lines that are only sequences of '[' and/or ']'
            if re.fullmatch(r"\s*[\[\]]+\s*", ln):
                continue
            cleaned.append(ln)
        result = "\n".join(cleaned)
        result = re.sub(r"\n{3,}", "\n\n", result)
        return result.strip()

    def _collect_children(self, node: Tag, base_url: str, article_folder: str) -> List[str]:
        buf: List[str] = []
        for ch in node.children:
            if isinstance(ch, NavigableString):
                txt = self._escape_md(str(ch))
                if txt:
                    buf.append(txt)
            elif isinstance(ch, Tag):
                name = ch.name.lower()
                if name == 'img':
                    img_md = self._handle_image(ch, base_url, article_folder)
                    if img_md:
                        buf.append(img_md)
                elif name == 'a':
                    # Drop external link, keep text only
                    buf.append(self._collect_inline_text(ch))
                elif name == 'pre':
                    code_tag = ch.find('code')
                    code_text = code_tag.get_text() if code_tag else ch.get_text()
                    language = self._detect_code_language(ch, code_tag)
                    buf.extend(self._fence_code_block(code_text, language))
                else:
                    nested = self._collect_children(ch, base_url, article_folder)
                    buf.extend(nested)
        return buf

    def _collect_inline(self, node: Tag, base_url: str, article_folder: str) -> str:
        parts: List[str] = []
        for ch in node.children:
            if isinstance(ch, NavigableString):
                parts.append(self._escape_md(str(ch)))
            elif isinstance(ch, Tag):
                nm = ch.name.lower()
                if nm == 'strong' or nm == 'b':
                    parts.append(f"**{self._collect_inline_text(ch)}**")
                elif nm == 'em' or nm == 'i':
                    parts.append(f"*{self._collect_inline_text(ch)}*")
                elif nm == 'code':
                    parts.append(self._inline_code_span(self._collect_inline_text(ch)))
                elif nm == 'img':
                    img_md = self._handle_image(ch, base_url, article_folder)
                    if img_md:
                        parts.append(img_md)
                elif nm == 'a':
                    # Remove link, keep visible text
                    parts.append(self._collect_inline_text(ch))
                else:
                    parts.append(self._collect_inline(ch, base_url, article_folder))
        # Collapse whitespace
        text = re.sub(r'\s+', ' ', ''.join(parts)).strip()
        return text

    def _collect_inline_text(self, node: Tag) -> str:
        text = node.get_text(separator=' ', strip=True)
        text = re.sub(r'\s+', ' ', text)
        return self._escape_md(text)

    def _escape_md(self, text: str) -> str:
        # Escape markdown special chars minimally
        return text.replace('*', '\\*').replace('_', '\\_').replace('#', '\\#')

    def _handle_image(self, img: Tag, base_url: str, article_folder: str) -> Optional[str]:
        # Skip images if no_images is True
        if self.no_images:
            return None
            
        # Resolve URL
        src = img.get('src') or img.get('data-src') or ''
        if not src:
            return None
        src = urljoin(base_url, src)

        # Filter static image types
        allowed_ext = ('.webp', '.jpg', '.jpeg', '.png', '.gif', '.svg')
        parsed = urlparse(src)
        path = parsed.path or ''
        if not any(path.lower().endswith(ext) for ext in allowed_ext):
            return None

        # Heuristics to skip ads/tracking
        classes = ' '.join(img.get('class', [])).lower()
        if 'ad' in classes or 'advert' in classes:
            return None
        try:
            width = int(img.get('width', '0'))
            height = int(img.get('height', '0'))
            if (width and width < 32) or (height and height < 32):
                return None
        except Exception:
            pass

        alt = (img.get('alt') or '').strip() or 'image'

        # Download image with verbose output
        local_name = self._unique_image_filename(article_folder, path)
        local_path = os.path.join(article_folder, local_name)
        try:
            if self.verbose:
                print(f"Downloading image: {src}")
            self._download_binary(src, local_path)
            if self.verbose:
                print(f"  → Saved as: {local_name}")
        except Exception as e:
            if self.verbose:
                print(f"  → Failed: {e}")
            return None

        # Return markdown image reference with newline
        return f"![{self._escape_md(alt)}]({local_name})\n"

    def _unique_image_filename(self, folder: str, remote_path: str) -> str:
        base = os.path.basename(remote_path) or 'image'
        base = re.sub(r'[^a-zA-Z0-9\._\-]', '_', base)
        name, ext = os.path.splitext(base)
        if not ext:
            ext = '.png'
        idx = 1
        candidate = f"img_{idx:03d}{ext}"
        while os.path.exists(os.path.join(folder, candidate)):
            idx += 1
            candidate = f"img_{idx:03d}{ext}"
        return candidate

    def _download_binary(self, url: str, dest: str) -> None:
        with requests.get(url, headers=self.headers, timeout=self.request_timeout, stream=True) as r:
            r.raise_for_status()
            with open(dest, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)


def main():
    """Command-line interface for the Article Exporter."""
    parser = argparse.ArgumentParser(
        description="Export articles from URLs to clean Markdown with local images",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s https://example.com/article
  %(prog)s --no-images https://example.com/article
  %(prog)s --verbose --output ./my-articles https://example.com/article
        """
    )
    
    parser.add_argument('url', help='URL of the article to export')
    parser.add_argument('--output', '-o', default='./articles',
                       help='Output directory for exported articles (default: ./articles)')
    parser.add_argument('--no-images', action='store_true',
                       help='Skip image downloads and remove image references from markdown')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Show detailed progress information')
    parser.add_argument('--timeout', '-t', type=int, default=30,
                       help='Request timeout in seconds (default: 30)')
    parser.add_argument('--delay', '-d', type=float, default=0.5,
                       help='Delay between requests in seconds (default: 0.5)')
    
    args = parser.parse_args()
    
    # Validate URL
    if not args.url.startswith(('http://', 'https://')):
        args.url = 'https://' + args.url
    
    try:
        # Create exporter with options
        exporter = ArticleExporter(
            output_root=args.output,
            request_timeout=args.timeout,
            request_delay=args.delay,
            no_images=args.no_images,
            verbose=args.verbose
        )
        
        # Create article from URL
        article = Article.from_url(args.url)
        
        if args.verbose:
            print(f"Starting export of: {args.url}")
            if args.no_images:
                print("Image downloads disabled")
            print(f"Output directory: {args.output}")
            print("-" * 50)
        
        # Export the article
        folder_path = exporter.export_article(article)
        
        if args.verbose:
            print("-" * 50)
            print(f"Export completed successfully!")
            print(f"Article saved to: {folder_path}")
            print(f"Markdown file: {os.path.join(folder_path, 'article.md')}")
        else:
            print(f"Article exported to: {folder_path}")
            
    except KeyboardInterrupt:
        print("\nExport cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()


