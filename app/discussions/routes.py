from flask import render_template, redirect, url_for, flash, request, Blueprint, jsonify, current_app
from flask_login import login_required, current_user
from app import db
from app.discussions.forms import CreateDiscussionForm
from app.models import Discussion
from app.utils import get_recent_activity
from app.middleware import track_discussion_view 
import json
import os


discussions_bp = Blueprint('discussions', __name__)

@discussions_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_discussion():
    form = CreateDiscussionForm()
    if form.validate_on_submit():
        # Create a new discussion
        discussion = Discussion(
            embed_code=form.embed_code.data,
            title=form.title.data,
            description=form.description.data,
            topic=form.topic.data,
            country=form.country.data,
            city=form.city.data,
            keywords=form.keywords.data,
            geographic_scope=form.geographic_scope.data,
            creator_id=current_user.id,
            individual_profile_id=current_user.individual_profile.id if current_user.profile_type == 'individual' else None,
            company_profile_id=current_user.company_profile.id if current_user.profile_type == 'company' else None
        )
        db.session.add(discussion)
        db.session.commit()
        flash("Discussion created successfully!", "success")

        # Redirect with both discussion_id and slug
        return redirect(url_for('discussions.view_discussion', discussion_id=discussion.id, slug=discussion.slug))

    return render_template('discussions/create_discussion.html', form=form)


@discussions_bp.route('/<int:discussion_id>/<slug>', methods=['GET'])
@track_discussion_view
def view_discussion(discussion_id, slug):
    discussion = Discussion.query.get_or_404(discussion_id)
    # Redirect if the slug in the URL doesn't match the discussion's slug
    if discussion.slug != slug:
        return redirect(url_for('discussions.view_discussion', 
                              discussion_id=discussion.id, 
                              slug=discussion.slug))
    # Render the page with embed_code directly
    return render_template('discussions/view_discussion.html', discussion=discussion)



def fetch_discussions(search, country, city, topic, keywords, page, per_page=9, sort='recent'):
    query = Discussion.query

    # Apply filters if provided
    if search:
        query = query.filter(Discussion.title.ilike(f"%{search}%"))
    if country:
        query = query.filter_by(country=country)
    if city:
        query = query.filter_by(city=city)
    if topic:
        query = query.filter_by(topic=topic)

    # Apply sorting
    if sort == 'recent':
        query = query.order_by(Discussion.created_at.desc())
    elif sort == 'popular':
        query = query.order_by(Discussion.participant_count.desc())  # Example for popular sorting

    return query.paginate(page=page, per_page=per_page)




@discussions_bp.route('/search', methods=['GET'])
def search_discussions():
    try:
        # Load city and country data
        json_path = os.path.join(current_app.root_path, 'static', 'data', 'cities_by_country.json')
        with open(json_path, 'r') as f:
            cities_by_country = json.load(f)
        countries = list(cities_by_country.keys())

        # Get search parameters
        search_term = request.args.get('q', '')
        topic = request.args.get('topic')
        country = request.args.get('country')
        city = request.args.get('city')
        keywords = request.args.get('keywords', '')
        page = request.args.get('page', 1, type=int)
        sort = request.args.get('sort', 'recent')  # Default to 'recent' if not specified

        # Use modified fetch_discussions to include sorting
        discussions = fetch_discussions(
            search=search_term,
            country=country,
            city=city,
            topic=topic,
            keywords=keywords,
            page=page,
            sort=sort  # Pass sort parameter here
        )

        return render_template(
            'discussions/search_discussions.html',
            discussions=discussions,
            search_term=search_term,
            countries=countries,
            cities_by_country=cities_by_country
        )

    except FileNotFoundError:
        current_app.logger.error(f"Could not find cities_by_country.json at {json_path}")
        return render_template(
            'discussions/search_discussions.html',
            discussions=None,
            search_term='',
            countries=[],
            cities_by_country={}
        )
    except Exception as e:
        current_app.logger.error(f"Error in search_discussions: {str(e)}")
        return render_template(
            'discussions/search_discussions.html',
            discussions=None,
            search_term='',
            countries=[],
            cities_by_country={}
        )



@discussions_bp.route('/api/search', methods=['GET'])
def api_search_discussions():
    try:
        # Get search parameters with defaults
        search = request.args.get('search', '')
        country = request.args.get('country', '')
        city = request.args.get('city', '')
        topic = request.args.get('topic', '')
        keywords = request.args.get('keywords', '')
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 12, type=int)  # Allow customizable page size

        # Validate page number
        if page < 1:
            return jsonify({
                'error': 'Invalid page number',
                'message': 'Page number must be greater than 0'
            }), 400

        # Get paginated discussions
        pagination = Discussion.search_discussions(
            search=search,
            country=country,
            city=city,
            topic=topic,
            keywords=keywords,
            page=page,
            per_page=per_page
        )

        # Prepare response
        response = {
            'status': 'success',
            'data': {
                'discussions': [d.to_dict() for d in pagination.items],
                'pagination': {
                    'total_items': pagination.total,
                    'total_pages': pagination.pages,
                    'current_page': pagination.page,
                    'per_page': per_page,
                    'has_next': pagination.has_next,
                    'has_prev': pagination.has_prev
                }
            },
            'meta': {
                'filters': {
                    'search': search,
                    'country': country,
                    'city': city,
                    'topic': topic,
                    'keywords': keywords
                }
            }
        }

        return jsonify(response), 200

    except ValueError as e:
        return jsonify({
            'status': 'error',
            'message': str(e),
            'error': 'Invalid parameter'
        }), 400

    except Exception as e:
        # Log the error here
        current_app.logger.error(f"Error in API search: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'An internal server error occurred',
            'error': 'Internal server error'
        }), 500

country_mapping = {
    "UK": "United Kingdom",
    "US": "United States",
    "AF": "Afghanistan",
    "AL": "Albania",
    "DZ": "Algeria",
    "AD": "Andorra",
    "AO": "Angola",
    "AG": "Antigua and Barbuda",
    "AR": "Argentina",
    "AM": "Armenia",
    "AU": "Australia",
    "AT": "Austria",
    "AZ": "Azerbaijan",
    "BS": "Bahamas",
    "BH": "Bahrain",
    "BD": "Bangladesh",
    "BB": "Barbados",
    "BY": "Belarus",
    "BE": "Belgium",
    "BZ": "Belize",
    "BJ": "Benin",
    "BT": "Bhutan",
    "BO": "Bolivia",
    "BA": "Bosnia and Herzegovina",
    "BW": "Botswana",
    "BR": "Brazil",
    "BN": "Brunei",
    "BG": "Bulgaria",
    "BF": "Burkina Faso",
    "BI": "Burundi",
    "CV": "Cabo Verde",
    "KH": "Cambodia",
    "CM": "Cameroon",
    "CA": "Canada",
    "CF": "Central African Republic",
    "TD": "Chad",
    "CL": "Chile",
    "CN": "China",
    "CO": "Colombia",
    "KM": "Comoros",
    "CG": "Congo",
    "CD": "Congo (DRC)",
    "CR": "Costa Rica",
    "CI": "Côte d'Ivoire",
    "HR": "Croatia",
    "CU": "Cuba",
    "CY": "Cyprus",
    "CZ": "Czech Republic",
    "DK": "Denmark",
    "DJ": "Djibouti",
    "DM": "Dominica",
    "DO": "Dominican Republic",
    "EC": "Ecuador",
    "EG": "Egypt",
    "SV": "El Salvador",
    "GQ": "Equatorial Guinea",
    "ER": "Eritrea",
    "EE": "Estonia",
    "SZ": "Eswatini",
    "ET": "Ethiopia",
    "FJ": "Fiji",
    "FI": "Finland",
    "FR": "France",
    "GA": "Gabon",
    "GM": "Gambia",
    "GE": "Georgia",
    "DE": "Germany",
    "GH": "Ghana",
    "GR": "Greece",
    "GD": "Grenada",
    "GT": "Guatemala",
    "GN": "Guinea",
    "GW": "Guinea-Bissau",
    "GY": "Guyana",
    "HT": "Haiti",
    "HN": "Honduras",
    "HU": "Hungary",
    "IS": "Iceland",
    "IN": "India",
    "ID": "Indonesia",
    "IR": "Iran",
    "IQ": "Iraq",
    "IE": "Ireland",
    "IL": "Israel",
    "IT": "Italy",
    "JM": "Jamaica",
    "JP": "Japan",
    "JO": "Jordan",
    "KZ": "Kazakhstan",
    "KE": "Kenya",
    "KI": "Kiribati",
    "KW": "Kuwait",
    "KG": "Kyrgyzstan",
    "LA": "Laos",
    "LV": "Latvia",
    "LB": "Lebanon",
    "LS": "Lesotho",
    "LR": "Liberia",
    "LY": "Libya",
    "LI": "Liechtenstein",
    "LT": "Lithuania",
    "LU": "Luxembourg",
    "MG": "Madagascar",
    "MW": "Malawi",
    "MY": "Malaysia",
    "MV": "Maldives",
    "ML": "Mali",
    "MT": "Malta",
    "MH": "Marshall Islands",
    "MR": "Mauritania",
    "MU": "Mauritius",
    "MX": "Mexico",
    "FM": "Micronesia",
    "MD": "Moldova",
    "MC": "Monaco",
    "MN": "Mongolia",
    "ME": "Montenegro",
    "MA": "Morocco",
    "MZ": "Mozambique",
    "MM": "Myanmar",
    "NA": "Namibia",
    "NR": "Nauru",
    "NP": "Nepal",
    "NL": "Netherlands",
    "NZ": "New Zealand",
    "NI": "Nicaragua",
    "NE": "Niger",
    "NG": "Nigeria",
    "NO": "Norway",
    "OM": "Oman",
    "PK": "Pakistan",
    "PW": "Palau",
    "PA": "Panama",
    "PG": "Papua New Guinea",
    "PY": "Paraguay",
    "PE": "Peru",
    "PH": "Philippines",
    "PL": "Poland",
    "PT": "Portugal",
    "QA": "Qatar",
    "RO": "Romania",
    "RU": "Russia",
    "RW": "Rwanda",
    "KN": "Saint Kitts and Nevis",
    "LC": "Saint Lucia",
    "VC": "Saint Vincent and the Grenadines",
    "WS": "Samoa",
    "SM": "San Marino",
    "ST": "Sao Tome and Principe",
    "SA": "Saudi Arabia",
    "SN": "Senegal",
    "RS": "Serbia",
    "SC": "Seychelles",
    "SL": "Sierra Leone",
    "SG": "Singapore",
    "SK": "Slovakia",
    "SI": "Slovenia",
    "SB": "Solomon Islands",
    "SO": "Somalia",
    "ZA": "South Africa",
    "KR": "South Korea",
    "SS": "South Sudan",
    "ES": "Spain",
    "LK": "Sri Lanka",
    "SD": "Sudan",
    "SR": "Suriname",
    "SE": "Sweden",
    "CH": "Switzerland",
    "SY": "Syria",
    "TW": "Taiwan",
    "TJ": "Tajikistan",
    "TZ": "Tanzania",
    "TH": "Thailand",
    "TL": "Timor-Leste",
    "TG": "Togo",
    "TO": "Tonga",
    "TT": "Trinidad and Tobago",
    "TN": "Tunisia",
    "TR": "Turkey",
    "TM": "Turkmenistan",
    "TV": "Tuvalu",
    "UG": "Uganda",
    "UA": "Ukraine",
    "AE": "United Arab Emirates",
    "UY": "Uruguay",
    "UZ": "Uzbekistan",
    "VU": "Vanuatu",
    "VE": "Venezuela",
    "VN": "Vietnam",
    "YE": "Yemen",
    "ZM": "Zambia",
    "ZW": "Zimbabwe"
}


@discussions_bp.route('/api/cities/<country_code>')
def get_cities_by_country(country_code):
    try:
        country_name = country_mapping.get(country_code, country_code)
        cities_by_country = current_app.config.get('CITIES_BY_COUNTRY', {})
        cities = cities_by_country.get(country_name, [])
        return jsonify(cities)
    except Exception as e:
        current_app.logger.error(f"Error in get_cities_by_country: {str(e)}")
        return jsonify({"error": str(e)}), 500
