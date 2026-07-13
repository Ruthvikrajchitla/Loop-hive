"""
LoopHive — Static Site Builder

Compiles markdown articles into a static HTML blog site using Jinja2.
Generates index.html, article pages, sitemap.xml, and custom CSS.
"""

from __future__ import annotations

import os
from pathlib import Path
import markdown
from jinja2 import Template
import structlog

logger = structlog.get_logger(__name__)


class StaticSiteBuilder:
    """Compiles local articles to a static blog folder."""

    def __init__(self, output_dir: str = "dist"):
        self.output_path = Path(output_dir)
        self.output_path.mkdir(exist_ok=True, parents=True)
        
        # Standard responsive template
        self.base_template = Template("""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }}</title>
    <meta name="description" content="{{ description }}">
    <style>
        body {
            font-family: 'Inter', system-ui, sans-serif;
            line-height: 1.6;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background: #0d0e15;
            color: #d1d2dc;
        }
        header {
            border-bottom: 1px solid #2a2c3f;
            padding-bottom: 20px;
            margin-bottom: 40px;
        }
        header h1 {
            background: linear-gradient(135deg, #a78bfa, #22d3ee);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin: 0;
        }
        nav a {
            color: #a78bfa;
            text-decoration: none;
            margin-right: 15px;
        }
        a { color: #22d3ee; text-decoration: none; }
        a:hover { text-decoration: underline; }
        article {
            background: #151726;
            padding: 30px;
            border-radius: 12px;
            border: 1px solid #2a2c3f;
            margin-bottom: 40px;
        }
        h2, h3 { color: #fff; }
        pre {
            background: #0d0e15;
            padding: 15px;
            border-radius: 8px;
            overflow-x: auto;
            border: 1px solid #2a2c3f;
        }
        code { font-family: monospace; color: #a78bfa; }
        blockquote {
            border-left: 4px solid #a78bfa;
            margin: 0;
            padding-left: 20px;
            color: #9ca3af;
            font-style: italic;
        }
        .footer {
            text-align: center;
            margin-top: 60px;
            color: #6b7280;
            font-size: 0.9em;
            border-top: 1px solid #2a2c3f;
            padding-top: 20px;
        }
    </style>
</head>
<body>
    <header>
        <h1>{{ site_name }}</h1>
        <nav>
            <a href="index.html">Home</a>
            <a href="about.html">About</a>
            <a href="privacy.html">Privacy Policy</a>
        </nav>
    </header>
    <main>
        {{ content }}
    </main>
    <div class="footer">
        <p>&copy; 2026 {{ site_name }}. Built autonomously by Otto.</p>
    </div>
</body>
</html>
        """)

    def build_site(self, site_name: str, articles: list[dict]):
        """Compile a list of article dictionaries to static HTML files."""
        logger.info("building_static_site", site=site_name, count=len(articles))

        # 1. Compile individual article pages
        post_items = []
        for idx, article in enumerate(articles):
            title = article.get("title", f"Post {idx}")
            body_md = article.get("body", "")
            desc = article.get("meta_description", "")
            
            # Convert markdown to html
            html_content = markdown.markdown(body_md, extensions=["fenced_code", "tables", "nl2br"])
            
            # Render page
            full_html = self.base_template.render(
                site_name=site_name,
                title=f"{title} | {site_name}",
                description=desc,
                content=f"<article><h1>{title}</h1>{html_content}</article>"
            )
            
            # Save file
            filename = f"post-{idx}.html"
            (self.output_path / filename).write_text(full_html, encoding="utf-8")
            
            # Keep index listing summary
            post_items.append(
                f'<li><a href="{filename}">{title}</a> - <small>{desc}</small></li>'
            )

        # 2. Build index.html page
        index_content = (
            f"<h2>Latest Articles</h2>"
            f"<ul>" + "\n".join(post_items) + "</ul>"
        )
        index_html = self.base_template.render(
            site_name=site_name,
            title=site_name,
            description="Welcome to our niche resource blog.",
            content=index_content
        )
        (self.output_path / "index.html").write_text(index_html, encoding="utf-8")

        # 3. Build boilerplate pages
        about_html = self.base_template.render(
            site_name=site_name,
            title=f"About Us | {site_name}",
            description="Learn more about our team and mission.",
            content="<h2>About Us</h2><p>This resource site is curated autonomously to deliver high-quality, compliance-audited tutorials and reviews in our niche.</p>"
        )
        (self.output_path / "about.html").write_text(about_html, encoding="utf-8")

        privacy_html = self.base_template.render(
            site_name=site_name,
            title=f"Privacy Policy | {site_name}",
            description="Our privacy and cookie policy.",
            content="<h2>Privacy Policy</h2><p>We respect your privacy. This site uses basic cookies to optimize traffic analytics and complies fully with standard ad network policies.</p>"
        )
        (self.output_path / "privacy.html").write_text(privacy_html, encoding="utf-8")

        # 4. Generate Sitemap.xml
        sitemap_lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
            '  <url><loc>https://loophive.app/index.html</loc></url>',
            '  <url><loc>https://loophive.app/about.html</loc></url>',
            '  <url><loc>https://loophive.app/privacy.html</loc></url>'
        ]
        for idx in range(len(articles)):
            sitemap_lines.append(f'  <url><loc>https://loophive.app/post-{idx}.html</loc></url>')
        sitemap_lines.append('</urlset>')
        
        (self.output_path / "sitemap.xml").write_text("\n".join(sitemap_lines), encoding="utf-8")

        logger.info("static_site_build_complete", output_dir=str(self.output_path))
