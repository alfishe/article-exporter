# Article Exporter

A standalone command-line tool to export articles from URLs to clean Markdown with local images.

## Features

- Fetches HTML content from any URL
- Automatically extracts article title and author from HTML content
- Extracts main article content, removing ads, navigation, and other clutter
- **Extracts and formats code blocks with language detection** when possible
- Downloads and embeds images locally
- Generates clean, readable Markdown with metadata
- Configurable output directory and options

## Installation

1. Clone or download this repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. The script `article_exporter.py` is ready to use from the root directory

## Usage

### Basic Usage

Export an article with images:
```bash
python article_exporter.py https://example.com/article
```

### Command Line Options

- `--no-images` - Skip image downloads and remove image references from markdown
- `--verbose, -v` - Show detailed progress information
- `--output, -o` - Specify output directory (default: `./articles`)
- `--timeout, -t` - Request timeout in seconds (default: 30)
- `--delay, -d` - Delay between requests in seconds (default: 0.5)

### Examples

Export without images:
```bash
python article_exporter.py --no-images https://example.com/article
```

Verbose export to custom directory:
```bash
python article_exporter.py --verbose --output ./my-articles https://example.com/article
```

Export with custom timeout and delay:
```bash
python article_exporter.py --timeout 60 --delay 1.0 https://example.com/article
```

## Output

The tool creates a unique folder for each article with the following structure:
```
output_directory/
└── YYYYMMDD-article-id-title/
    └── article.md
    └── img_001.jpg (if images enabled)
    └── img_002.png (if images enabled)
    └── ...
```

## Requirements

- Python 3.7+
- Internet connection for fetching articles
- Sufficient disk space for downloaded images

## Code Block Handling

The tool automatically detects and formats code blocks from HTML content:

- **Language Detection**: Attempts to identify programming languages from CSS classes and attributes
- **Proper Formatting**: Converts HTML `<pre><code>` blocks to properly fenced Markdown code blocks
- **Safe Fencing**: Uses dynamic fence lengths to avoid conflicts with code content
- **Language Tags**: Adds appropriate language identifiers for syntax highlighting when possible

Supported languages include JavaScript, Python, C++, HTML, CSS, SQL, and many more.

## Dependencies

- `beautifulsoup4` - HTML parsing and content extraction
- `requests` - HTTP requests and file downloads
- `lxml` - Fast XML/HTML parser backend
