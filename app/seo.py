# app/seo.py
from flask import Response, url_for, request, current_app
from datetime import datetime
from app.models import Discussion

def get_base_url():
    """Get the base URL depending on environment"""
    if request.headers.get('X-Forwarded-Proto'):
        return f"{request.scheme}://{request.headers['Host']}"
    return 'https://societyspeaks.io'

def generate_sitemap():
    """Generate the sitemap XML content with optimized priorities"""
    base_url = get_base_url()
    current_date = datetime.now().strftime("%Y-%m-%d")

    xml_content = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">',
        '  <!-- Main Pages -->',
        '  <url>',
        f'    <loc>{base_url}/</loc>',
        '    <priority>1.0</priority>',
        '    <changefreq>daily</changefreq>',
        '  </url>',
        '  <url>',
        f'    <loc>{base_url}/about</loc>',
        '    <priority>0.8</priority>',
        '    <changefreq>monthly</changefreq>',
        '  </url>',

        '  <!-- Discussions -->',
        '  <url>',
        f'    <loc>{base_url}/discussions</loc>',
        '    <priority>1.0</priority>',
        '    <changefreq>daily</changefreq>',
        '  </url>',
        '  <url>',
        f'    <loc>{base_url}/discussions/featured</loc>',
        '    <priority>0.9</priority>',
        '    <changefreq>daily</changefreq>',
        '  </url>',

        '  <!-- Discussion Categories -->',
    ]

    # Add category pages
    categories = ['healthcare', 'environment', 'education', 'technology', 'politics', 'society']
    for category in categories:
        category_entry = [
            '  <url>',
            f'    <loc>{base_url}/discussions/categories/{category}</loc>',
            '    <priority>0.8</priority>',
            '    <changefreq>daily</changefreq>',
            '  </url>'
        ]
        xml_content.extend(category_entry)

    # Add location-based pages
    xml_content.extend([
        '  <!-- Location-based Discussions -->',
        '  <url>',
        f'    <loc>{base_url}/discussions/location/global</loc>',
        '    <priority>0.8</priority>',
        '    <changefreq>daily</changefreq>',
        '  </url>',
        '  <url>',
        f'    <loc>{base_url}/discussions/location/country</loc>',
        '    <priority>0.8</priority>',
        '    <changefreq>daily</changefreq>',
        '  </url>',
        '  <url>',
        f'    <loc>{base_url}/discussions/location/city</loc>',
        '    <priority>0.8</priority>',
        '    <changefreq>daily</changefreq>',
        '  </url>'
    ])

    # Add user features
    xml_content.extend([
        '  <!-- User Features -->',
        '  <url>',
        f'    <loc>{base_url}/start-discussion</loc>',
        '    <priority>0.8</priority>',
        '    <changefreq>monthly</changefreq>',
        '  </url>'
    ])

    # Add support and information pages
    xml_content.extend([
        '  <!-- Support & Information -->',
        '  <url>',
        f'    <loc>{base_url}/support</loc>',
        '    <priority>0.7</priority>',
        '    <changefreq>monthly</changefreq>',
        '  </url>',
        '  <url>',
        f'    <loc>{base_url}/donate</loc>',
        '    <priority>0.7</priority>',
        '    <changefreq>monthly</changefreq>',
        '  </url>'
    ])

    # Add legal pages
    xml_content.extend([
        '  <!-- Legal Pages -->',
        '  <url>',
        f'    <loc>{base_url}/privacy-policy</loc>',
        '    <priority>0.5</priority>',
        '    <changefreq>monthly</changefreq>',
        '  </url>',
        '  <url>',
        f'    <loc>{base_url}/terms-and-conditions</loc>',
        '    <priority>0.5</priority>',
        '    <changefreq>monthly</changefreq>',
        '  </url>',
        '  <url>',
        f'    <loc>{base_url}/content-policy</loc>',
        '    <priority>0.5</priority>',
        '    <changefreq>monthly</changefreq>',
        '  </url>'
    ])

    
    # Add News section
    xml_content.extend([
        '  <!-- News Discussions -->',
        '  <url>',
        f'    <loc>{base_url}/discussions/news</loc>',
        '    <priority>0.9</priority>',
        '    <changefreq>hourly</changefreq>',
        '  </url>'
    ])

    # Add help and resources
    xml_content.extend([
        '  <!-- Help & Resources -->',
        '  <url>',
        f'    <loc>{base_url}/help</loc>',
        '    <priority>0.7</priority>',
        '    <changefreq>weekly</changefreq>',
        '  </url>',
        '  <url>',
        f'    <loc>{base_url}/help/getting-started</loc>',
        '    <priority>0.7</priority>',
        '    <changefreq>weekly</changefreq>',
        '  </url>',
        '  <url>',
        f'    <loc>{base_url}/help/creating-discussions</loc>',
        '    <priority>0.7</priority>',
        '    <changefreq>weekly</changefreq>',
        '  </url>',
        '  <url>',
        f'    <loc>{base_url}/help/managing-discussions</loc>',
        '    <priority>0.7</priority>',
        '    <changefreq>weekly</changefreq>',
        '  </url>',
        '  <url>',
        f'    <loc>{base_url}/help/seed-comments</loc>',
        '    <priority>0.7</priority>',
        '    <changefreq>weekly</changefreq>',
        '  </url>',
        '  <url>',
        f'    <loc>{base_url}/help/polis-algorithms</loc>',
        '    <priority>0.7</priority>',
        '    <changefreq>weekly</changefreq>',
        '  </url>',
        '  <url>',
        f'    <loc>{base_url}/help/native-system</loc>',
        '    <priority>0.7</priority>',
        '    <changefreq>weekly</changefreq>',
        '  </url>',
        '  <url>',
        f'    <loc>{base_url}/help/news-feed</loc>',
        '    <priority>0.7</priority>',
        '    <changefreq>weekly</changefreq>',
        '  </url>',
        '  <url>',
        f'    <loc>{base_url}/faq</loc>',
        '    <priority>0.6</priority>',
        '    <changefreq>monthly</changefreq>',
        '  </url>',
        '  <url>',
        f'    <loc>{base_url}/contact</loc>',
        '    <priority>0.6</priority>',
        '    <changefreq>monthly</changefreq>',
        '  </url>'
    ])

    # Add dynamic discussions if they exist
    try:
        discussions = Discussion.query.all()
        if discussions:
            xml_content.append('  <!-- Dynamic Discussions -->')
            for discussion in discussions:
                discussion_entry = [
                    '  <url>',
                    f'    <loc>{base_url}/discussion/{discussion.id}</loc>',
                    f'    <lastmod>{discussion.updated_at.strftime("%Y-%m-%d")}</lastmod>',
                    '    <priority>0.7</priority>',
                    '    <changefreq>daily</changefreq>',
                    '  </url>'
                ]
                xml_content.extend(discussion_entry)
    except Exception as e:
        current_app.logger.error(f"Error adding discussions to sitemap: {e}")

    # Close the XML
    xml_content.append('</urlset>')

    # Join all lines with newlines
    return '\n'.join(xml_content)