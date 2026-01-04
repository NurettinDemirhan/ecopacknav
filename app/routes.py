# app/routes.py
from flask import Blueprint, render_template, redirect, url_for, flash
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired
from werkzeug.security import check_password_hash
from flask_login import login_user, logout_user, login_required, UserMixin, current_user
from bson.objectid import ObjectId
from flask import request, jsonify
from . import mongo, login_manager
from datetime import datetime, timezone
import math

main_bp = Blueprint("main", __name__)

# --- Helpers ---
def _safe_float(value):
    try:
        return float(value) if value not in (None, '') else None
    except (TypeError, ValueError):
        return None

def calculate_volume(shape, dimensions):
    """Return volume in cm^3 for supported shapes, or None if inputs are incomplete."""
    if shape == 'rectangular':
        length = _safe_float(dimensions.get('length'))
        width = _safe_float(dimensions.get('width'))
        height = _safe_float(dimensions.get('height'))
        if None not in (length, width, height):
            return length * width * height
    elif shape == 'cylinder':
        radius = _safe_float(dimensions.get('radius'))
        height = _safe_float(dimensions.get('height'))
        if None not in (radius, height):
            return math.pi * (radius ** 2) * height
    elif shape == 'sphere':
        radius = _safe_float(dimensions.get('radius'))
        if radius is not None:
            return (4 / 3) * math.pi * (radius ** 3)
    elif shape == 'other':
        volume = _safe_float(dimensions.get('volume'))
        if volume is not None:
            return volume
    return None

def _log_activity(activity_type: str, description: str):
    """Inserts an activity record for the current user."""
    try:
        mongo.db.activities.insert_one({
            "owner": ObjectId(current_user.id),
            "type": activity_type,
            "description": description,
            "timestamp": datetime.now(timezone.utc)
        })
    except Exception as e:
        # In a real app, you might want to log this error to a file
        print(f"Failed to log activity: {e}")

# --- User model ---
class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data.get("_id"))  # flask-login string sever
        self.username = user_data.get("username")

    def get_username(self):
        return self.username

@login_manager.user_loader
def load_user(user_id):
    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    return User(user) if user else None

# --- WTForm ---
class LoginForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Log In")

@main_bp.route("/", methods=["GET", "POST"])
def login():
    login_form = LoginForm()
    if login_form.validate_on_submit():
        username = login_form.username.data
        raw_password = login_form.password.data

        user = mongo.db.users.find_one({"username": username})
        if user:
            if check_password_hash(user["password"], raw_password):
                login_user(User(user))
                return redirect(url_for("main.dashboard"))
            flash("Incorrect password.", "danger")
        else:
            flash("Username not found.", "warning")

        return redirect(url_for("main.login"))

   
    return render_template("login_page.html", login_form=login_form)


def pick_material_text(pkg: dict) -> str:
    """
    materials array varsa içinden material adlarını birleştir.
    Yoksa pkg['material'] veya pkg['materials'] string gibi alanlara düş.
    """
    mats = pkg.get("materials")
    if isinstance(mats, list) and mats:
        names = []
        for m in mats:
            if isinstance(m, dict):
                val = (m.get("material") or m.get("material_type") or m.get("plastic_type") or "").strip()
                if val:
                    names.append(val)
            elif isinstance(m, str) and m.strip():
                names.append(m.strip())
        # uniq + kısa
        uniq = []
        for n in names:
            if n not in uniq:
                uniq.append(n)
        return ", ".join(uniq[:3]) if uniq else "—"

    return (pkg.get("material") or "—")

def pick_component_type_text(pkg: dict) -> str:
    mats = pkg.get("materials")
    if isinstance(mats, list) and mats:
        names = []
        for m in mats:
            if isinstance(m, dict):
                val = (m.get("package_component") or "").strip()
                if val:
                    names.append(val)
        # Get unique component types
        uniq = []
        for n in names:
            if n not in uniq:
                uniq.append(n)
        return ", ".join(uniq[:3]) if uniq else "—"
    return "—"

@main_bp.get("/products")
@login_required
def products():
    user_oid = ObjectId(current_user.id)

    # --- Products (user'a ait) ---
    products = list(
        mongo.db.products.find(
            {"owner": user_oid},
            {"product_code": 1, "secondary_product_code": 1, "connections": 1, "product_category": 1, "product_description": 1, "product_material": 1, "product_shape": 1, "volume_cm3": 1, "product_volume": 1}
        ).sort("product_code", 1)
    )

    for product in products:
        connections = product.get("connections", {})
        missing_count = 0
        
        # Check for empty or non-existent values
        if not connections.get("primary_package"):
            missing_count += 1
        if not connections.get("secondary_package"):
            missing_count += 1
        if not connections.get("tertiary_package"):
            missing_count += 1
        
        if missing_count == 0:
            product["packaging_status"] = "Connected"
            product["packaging_status_color"] = "green"
        else:
            product["packaging_status"] = f"Missing ({missing_count})"
            product["packaging_status_color"] = "red"


    # --- Packaging collections (user'a ait) ---
    primary = list(mongo.db.primary_packagings.find({"owner": user_oid}))
    secondary = list(mongo.db.secondary_packagings.find({"owner": user_oid}))
    tertiary = list(mongo.db.tertiary_packagings.find({"owner": user_oid}))

    partners = list(mongo.db.partners.find({"owner": user_oid}))
    supplier_map = {str(p["_id"]): p.get("partner_name", "Unknown") for p in partners}

    def pick_supplier_text(pkg: dict) -> str:
        supplier_id = pkg.get("supplier")
        if supplier_id and str(supplier_id) in supplier_map:
            return supplier_map[str(supplier_id)]
        return "—"

    def normalize(pkg: dict, level: str) -> dict:
        return {
            "_id": str(pkg.get("_id")),
            "package_code": pkg.get("package_code") or pkg.get("code") or "—",
            "level": level,  # Primary / Secondary / Tertiary
            "component_type": pick_component_type_text(pkg),
            "material": pick_material_text(pkg),
            "supplier": pick_supplier_text(pkg),
            # Bu doc tek bir product'a bağlıysa product_code üzerinden 1 sayabiliriz.
            # Eğer doc içinde product_codes listesi varsa onu say.
            "products_using": (
                len(pkg.get("connections", []))
            ),
            "recyclability": (pkg.get("recyclability") or "—"),
        }

    packaging_rows = (
        [normalize(p, "Primary") for p in primary] +
        [normalize(p, "Secondary") for p in secondary] +
        [normalize(p, "Tertiary") for p in tertiary]
    )

    all_primary_packagings = list(mongo.db.primary_packagings.find({"owner": user_oid}))
    all_secondary_packagings = list(mongo.db.secondary_packagings.find({"owner": user_oid}))
    all_tertiary_packagings = list(mongo.db.tertiary_packagings.find({"owner": user_oid}))
    
    # Fetch data setup items
    component_types = list(mongo.db.component_types.find({"owner": user_oid}).sort("name", 1))
    adhesives = list(mongo.db.adhesives.find({"owner": user_oid}).sort("name", 1))
    food_contacts = list(mongo.db.food_contacts.find({"owner": user_oid}).sort("name", 1))
    coatings = list(mongo.db.coatings.find({"owner": user_oid}).sort("name", 1))

    return render_template(
        "products_page.html",
        products=products,
        packaging_rows=packaging_rows,
        partners=partners,
        all_primary_packagings=all_primary_packagings,
        all_secondary_packagings=all_secondary_packagings,
        all_tertiary_packagings=all_tertiary_packagings,
        component_types=component_types,
        adhesives=adhesives,
        food_contacts=food_contacts,
        coatings=coatings
    )


@main_bp.route("/add_product", methods=["POST"])
@login_required
def add_product():
    try:
        created_at = datetime.now(timezone.utc)
        owner_id = ObjectId(current_user.id)

        product_code = request.form.get('productCode')
        secondary_product_code = request.form.get('secondaryProductCode')
        product_category = request.form.get('productCategory')
        product_description = request.form.get('productDescription')
        product_material = request.form.get('material')

        if not product_code or not product_material:
            flash('Product Code and Material are required.', 'danger')
            return redirect(url_for("main.products"))

        new_product = {
            'product_code': product_code,
            'secondary_product_code': secondary_product_code,
            'product_category': product_category,
            'product_description': product_description,
            'product_material': product_material,
            'owner': owner_id,
            'creation_time': created_at,
            'dimensions': {},
            'sales': [],
            'connections': {
                'primary_package': '',
                'secondary_package': '',
                'tertiary_package': ''
            }
        }

        if product_material == 'solid':
            product_shape = request.form.get('productShape')
            new_product['product_shape'] = product_shape
            dimensions = {}
            if product_shape == 'rectangular':
                dimensions['length'] = request.form.get('length')
                dimensions['width'] = request.form.get('width')
                dimensions['height'] = request.form.get('height')
            elif product_shape == 'cylinder':
                dimensions['height'] = request.form.get('cylHeight')
                dimensions['radius'] = request.form.get('cylRadius')
            elif product_shape == 'sphere':
                dimensions['radius'] = request.form.get('sphRadius')
            elif product_shape == 'other':
                dimensions['volume'] = request.form.get('volume')
            
            new_product['dimensions'] = dimensions
            new_product['volume_cm3'] = calculate_volume(product_shape, dimensions)

        elif product_material == 'liquid/gas':
            product_volume = request.form.get('productVolume')
            new_product['product_volume'] = product_volume
        
        mongo.db.products.insert_one(new_product)
        _log_activity("product_creation", f"Created product: {product_code}")

        flash(f'Product "{product_code}" has been created successfully!', 'success')
    except Exception as e:
        flash(f'An error occurred: {str(e)}', 'danger')

    return redirect(url_for("main.products"))


@main_bp.route("/update_product/<product_id>", methods=["POST"])
@login_required
def update_product(product_id):
    try:
        product_oid = ObjectId(product_id)
        owner_oid = ObjectId(current_user.id)

        # Check if product exists and belongs to user
        product = mongo.db.products.find_one({"_id": product_oid, "owner": owner_oid})
        if not product:
            flash("Product not found or access denied.", "danger")
            return redirect(url_for("main.products"))

        product_code = request.form.get('productCode')
        product_material = request.form.get('material')

        if not product_code or not product_material:
            flash('Product Code and Material are required.', 'danger')
            return redirect(url_for("main.products"))

        update_doc = {
            'product_code': product_code,
            'secondary_product_code': request.form.get('secondaryProductCode'),
            'product_category': request.form.get('productCategory'),
            'product_description': request.form.get('productDescription'),
            'product_material': product_material,
            'dimensions': {},
            'volume_cm3': None,
            'product_volume': None,
            'product_shape': None
        }

        if product_material == 'solid':
            product_shape = request.form.get('productShape')
            update_doc['product_shape'] = product_shape
            dimensions = {}
            if product_shape == 'rectangular':
                dimensions['length'] = request.form.get('length')
                dimensions['width'] = request.form.get('width')
                dimensions['height'] = request.form.get('height')
            elif product_shape == 'cylinder':
                dimensions['height'] = request.form.get('cylHeight')
                dimensions['radius'] = request.form.get('cylRadius')
            elif product_shape == 'sphere':
                dimensions['radius'] = request.form.get('sphRadius')
            elif product_shape == 'other':
                dimensions['volume'] = request.form.get('volume')
            
            update_doc['dimensions'] = dimensions
            update_doc['volume_cm3'] = calculate_volume(product_shape, dimensions)

        elif product_material == 'liquid/gas':
            product_volume = request.form.get('productVolume')
            update_doc['product_volume'] = product_volume

        mongo.db.products.update_one(
            {'_id': product_oid},
            {'$set': update_doc}
        )

        # If product code was changed, we must update denormalized data in packaging
        if product.get('product_code') != product_code:
            product_id_str = str(product_oid)
            collections = [
                mongo.db.primary_packagings,
                mongo.db.secondary_packagings,
                mongo.db.tertiary_packagings
            ]
            for coll in collections:
                coll.update_many(
                    {'connections._id': product_id_str},
                    {'$set': {'connections.$.product_code': product_code}}
                )


        _log_activity("product_update", f"Updated product: {product_code}")
        flash(f'Product "{product_code}" has been updated successfully!', 'success')

    except Exception as e:
        flash(f'An error occurred while updating the product: {str(e)}', 'danger')

    return redirect(url_for("main.products"))



@main_bp.route("/add_packaging", methods=["POST"])
@login_required
def add_packaging():
    try:
        # --- Basic Info ---
        level = request.form.get('packagingLevel')
        package_code = request.form.get('packageCode')
        recyclability = request.form.get('recyclability')
        package_shape = request.form.get('packageShape')

        if not all([level, package_code]):
            flash('Level and Code are required.', 'danger')
            return redirect(url_for("main.products"))

        # --- Dimensions ---
        dimensions = {}
        if package_shape == 'rectangular':
            dimensions['length'] = request.form.get('length')
            dimensions['width'] = request.form.get('width')
            dimensions['height'] = request.form.get('height')
        elif package_shape == 'cylinder':
            dimensions['height'] = request.form.get('cylHeight')
            dimensions['radius'] = request.form.get('cylRadius')
        elif package_shape == 'sphere':
            dimensions['radius'] = request.form.get('sphRadius')
        elif package_shape == 'other':
            dimensions['volume'] = request.form.get('volume')
        
        # --- Material Composition ---
        components = request.form.getlist('packageComponent[]')
        materials = request.form.getlist('material[]')
        weights = request.form.getlist('weightGrams[]')
        recycled_contents = request.form.getlist('recycledContent[]')
        thicknesses = request.form.getlist('thicknessMicrons[]')
        adhesives = request.form.getlist('adhesiveType[]')
        food_contacts = request.form.getlist('foodContact[]')
        coatings = request.form.getlist('coatingType[]')

        materials_list = []
        for i in range(len(components)):
            if not components[i]: continue # Skip empty component rows
            materials_list.append({
                "package_component": components[i],
                "material": materials[i],
                "weight_grams": _safe_float(weights[i]),
                "recycled_content": _safe_float(recycled_contents[i]),
                "thickness_microns": _safe_float(thicknesses[i]),
                "adhesive_type": adhesives[i],
                "food_contact": food_contacts[i],
                "coating": coatings[i]
            })
            
        # --- Document Assembly ---
        doc = {
            'package_code': package_code,
            'package_shape': package_shape,
            'dimensions': dimensions,
            'materials': materials_list,
            'recyclability': recyclability,
            'volume_cm3': calculate_volume(package_shape, dimensions),
            'owner': ObjectId(current_user.id),
            'creation_time': datetime.now(timezone.utc)
        }
        
        # --- DB Insertion ---
        collection = None
        if level == 'Primary':
            collection = mongo.db.primary_packagings
        elif level == 'Secondary':
            collection = mongo.db.secondary_packagings
            doc['quantity_primary_in_secondary_unit'] = _safe_float(request.form.get('quantity_primary_in_secondary_unit'))
        elif level == 'Tertiary':
            collection = mongo.db.tertiary_packagings
            doc['quantity_secondary_in_tertiary_unit'] = _safe_float(request.form.get('quantity_secondary_in_tertiary_unit'))

        if collection is not None:
            collection.insert_one(doc)
            _log_activity("packaging_creation", f"Created {level} packaging: {package_code}")
            flash(f'{level} packaging "{package_code}" has been created successfully!', 'success')
        else:
            flash(f'Invalid packaging level: {level}', 'danger')

    except Exception as e:
        flash(f'An error occurred: {str(e)}', 'danger')

    return redirect(url_for("main.products"))


@main_bp.route("/add_partner", methods=["POST"])
@login_required
def add_partner():
    try:
        partner_type = request.form.get('partner_type')
        partner_name = request.form.get('partner_name')

        if not partner_type or not partner_name:
            flash('Partner Type and Partner Name are required.', 'danger')
            return redirect(url_for("main.products"))

        new_partner = {
            'partner_type': partner_type,
            'partner_name': partner_name,
            'email': request.form.get('email'),
            'phone_number': request.form.get('phone_number'),
            'address': request.form.get('address'),
            'country': request.form.get('country'),
            'connections': [],
            'owner': ObjectId(current_user.id),
            'creation_time': datetime.now(timezone.utc)
        }
        
        mongo.db.partners.insert_one(new_partner)
        _log_activity("partner_creation", f"Created {partner_type}: {partner_name}")

        flash(f'Partner "{partner_name}" has been created successfully!', 'success')
    except Exception as e:
        flash(f'An error occurred: {str(e)}', 'danger')

    return redirect(url_for("main.products"))


@main_bp.route("/update_product_packaging_connections/<product_id>", methods=["POST"])
@login_required
def update_product_packaging_connections(product_id):
    try:
        product_oid = ObjectId(product_id)
        owner_oid = ObjectId(current_user.id)

        product = mongo.db.products.find_one({"_id": product_oid, "owner": owner_oid})
        if not product:
            flash("Product not found.", "danger")
            referer = request.headers.get('Referer', '')
            if '/dashboard' in referer:
                return redirect(url_for("main.dashboard"))
            return redirect(url_for("main.products"))

        old_connections = product.get("connections", {})
        product_info = { "_id": str(product["_id"]), "product_code": product["product_code"] }

        # Get new connections from form
        new_primary_id = request.form.get("primary_package")
        new_secondary_id = request.form.get("secondary_package")
        new_tertiary_id = request.form.get("tertiary_package")

        # --- Update Product's connections ---
        mongo.db.products.update_one(
            {"_id": product_oid},
            {"$set": {
                "connections.primary_package": new_primary_id,
                "connections.secondary_package": new_secondary_id,
                "connections.tertiary_package": new_tertiary_id
            }}
        )

        # --- Helper to manage two-way binding ---
        def update_packaging_connection(collection, old_pkg_id_str, new_pkg_id_str, product_info_to_link):
            product_id_str_to_link = product_info_to_link['_id']

            # Remove from old packaging
            if old_pkg_id_str and old_pkg_id_str != new_pkg_id_str:
                try:
                    collection.update_one(
                        {"_id": ObjectId(old_pkg_id_str)},
                        {"$pull": {"connections": {'_id': product_id_str_to_link}}}
                    )
                except:
                    pass # Ignore if old ID is invalid
            
            # Add to new packaging
            if new_pkg_id_str and old_pkg_id_str != new_pkg_id_str:
                try:
                    link_doc = {'_id': product_id_str_to_link, 'product_code': product_info_to_link['product_code']}
                    
                    # First remove any old link for this product to prevent duplicates if logic ever changes
                    collection.update_one(
                        {"_id": ObjectId(new_pkg_id_str)},
                        {"$pull": {"connections": {'_id': product_id_str_to_link}}}
                    )
                    # Then add the new, updated link
                    collection.update_one(
                        {"_id": ObjectId(new_pkg_id_str)},
                        {"$push": {"connections": link_doc}}
                    )
                except:
                    pass # Ignore if new ID is invalid

        # --- Apply updates for each level ---
        update_packaging_connection(mongo.db.primary_packagings, old_connections.get("primary_package"), new_primary_id, product_info)
        update_packaging_connection(mongo.db.secondary_packagings, old_connections.get("secondary_package"), new_secondary_id, product_info)
        update_packaging_connection(mongo.db.tertiary_packagings, old_connections.get("tertiary_package"), new_tertiary_id, product_info)
        
        _log_activity("connection_update", f"Updated packaging connections for product: {product['product_code']}")
        flash("Packaging connections updated successfully!", "success")

    except Exception as e:
        flash(f"An error occurred: {str(e)}", "danger")

    # Redirect based on referer
    referer = request.headers.get('Referer', '')
    if '/dashboard' in referer:
        return redirect(url_for("main.dashboard"))
    return redirect(url_for("main.products"))


@main_bp.route("/update_product_customer_connection/<product_id>", methods=["POST"])
@login_required
def update_product_customer_connection(product_id):
    try:
        product_oid = ObjectId(product_id)
        owner_oid = ObjectId(current_user.id)

        product = mongo.db.products.find_one({"_id": product_oid, "owner": owner_oid})
        if not product:
            flash("Product not found.", "danger")
            referer = request.headers.get('Referer', '')
            if '/dashboard' in referer:
                return redirect(url_for("main.dashboard"))
            return redirect(url_for("main.products"))

        old_customer_id = product.get("connections", {}).get("customer")
        new_customer_id = request.form.get("customer")

        # Update product's customer connection
        mongo.db.products.update_one(
            {"_id": product_oid},
            {"$set": {"connections.customer": new_customer_id}}
        )

        # Remove product from old customer's connections
        if old_customer_id and old_customer_id != new_customer_id:
            try:
                mongo.db.partners.update_one(
                    {"_id": ObjectId(old_customer_id)},
                    {"$pull": {"connections": product_oid}}
                )
            except:
                pass # Ignore errors for invalid old IDs

        # Add product to new customer's connections
        if new_customer_id and old_customer_id != new_customer_id:
            try:
                mongo.db.partners.update_one(
                    {"_id": ObjectId(new_customer_id)},
                    {"$addToSet": {"connections": product_oid}}
                )
            except:
                pass # Ignore errors for invalid new IDs

        _log_activity("connection_update", f"Updated customer connection for product: {product['product_code']}")
        flash("Customer connection updated successfully!", "success")

    except Exception as e:
        flash(f"An error occurred: {str(e)}", "danger")

    # Redirect based on referer
    referer = request.headers.get('Referer', '')
    if '/dashboard' in referer:
        return redirect(url_for("main.dashboard"))
    return redirect(url_for("main.products"))


@main_bp.route("/update_packaging_product_connections", methods=["POST"])
@login_required
def update_packaging_product_connections():
    try:
        owner_oid = ObjectId(current_user.id)
        package_id_str = request.form.get("package_id")
        package_level = request.form.get("package_level")
        new_product_ids_str = request.form.getlist("product_ids")

        package_oid = ObjectId(package_id_str)
        new_product_oids = [ObjectId(pid) for pid in new_product_ids_str]

        collections = {
            "Primary": mongo.db.primary_packagings,
            "Secondary": mongo.db.secondary_packagings,
            "Tertiary": mongo.db.tertiary_packagings
        }
        package_collection = collections.get(package_level)
        connection_field = f"connections.{package_level.lower()}_package"

        if package_collection is None:
            flash("Invalid packaging level.", "danger")
            referer = request.headers.get('Referer', '')
            if '/dashboard' in referer:
                return redirect(url_for("main.dashboard"))
            return redirect(url_for("main.products"))

        # Get the package's current connections to find which products to unlink
        package = package_collection.find_one({"_id": package_oid})
        # Note: This is complex because connections can be in multiple formats.
        # We find all old product IDs regardless of format to ensure they can be unlinked.
        old_product_ids = []
        if package and "connections" in package:
            for link in package.get("connections", []):
                try:
                    if isinstance(link, ObjectId):
                        old_product_ids.append(link)
                    elif isinstance(link, dict) and '_id' in link:
                        old_product_ids.append(ObjectId(link['_id']))
                    elif isinstance(link, dict) and '$oid' in link:
                        old_product_ids.append(ObjectId(link['$oid']))
                except:
                    pass
        
        # --- Main Logic ---
        # 1. Find which products are being removed and unlink them from this package
        ids_to_unlink = [old_id for old_id in old_product_ids if old_id not in new_product_oids]
        if ids_to_unlink:
            mongo.db.products.update_many(
                {"_id": {"$in": ids_to_unlink}},
                {"$set": {connection_field: ""}}
            )

        # 2. Link all new products to this package in the products collection
        if new_product_oids:
            mongo.db.products.update_many(
                {"_id": {"$in": new_product_oids}},
                {"$set": {connection_field: package_id_str}}
            )

        # 3. Create the new denormalized list for the package's own connections field
        products_to_link_cursor = mongo.db.products.find(
            {"_id": {"$in": new_product_oids}},
            {"product_code": 1}
        )
        new_connections_list = [
            {'_id': str(p['_id']), 'product_code': p['product_code']}
            for p in products_to_link_cursor
        ]

        # 4. Atomically update the package's own connection list
        package_collection.update_one(
            {"_id": package_oid},
            {"$set": {"connections": new_connections_list}}
        )

        _log_activity("connection_update", f"Updated product connections for packaging: {package.get('package_code', 'N/A')}")
        flash("Packaging connections updated successfully!", "success")

    except Exception as e:
        flash(f"An error occurred: {str(e)}", "danger")

    # Redirect based on referer
    referer = request.headers.get('Referer', '')
    if '/dashboard' in referer:
        return redirect(url_for("main.dashboard"))
    return redirect(url_for("main.products"))


@main_bp.route("/update_packaging_supplier_connection", methods=["POST"])
@login_required
def update_packaging_supplier_connection():
    try:
        package_id_str = request.form.get("package_id")
        package_level = request.form.get("package_level")
        new_supplier_id_str = request.form.get("supplier_id")
        
        package_oid = ObjectId(package_id_str)

        collections = {
            "Primary": mongo.db.primary_packagings,
            "Secondary": mongo.db.secondary_packagings,
            "Tertiary": mongo.db.tertiary_packagings
        }
        package_collection = collections.get(package_level)

        if package_collection is None:
            flash("Invalid packaging level.", "danger")
            referer = request.headers.get('Referer', '')
            if '/dashboard' in referer:
                return redirect(url_for("main.dashboard"))
            return redirect(url_for("main.products"))

        # Get old supplier to unlink later
        package = package_collection.find_one({"_id": package_oid})
        old_supplier_id_str = package.get("supplier")

        # Update package's supplier field
        package_collection.update_one(
            {"_id": package_oid},
            {"$set": {"supplier": new_supplier_id_str}}
        )

        # Remove package from old supplier's connections
        if old_supplier_id_str and old_supplier_id_str != new_supplier_id_str:
            try:
                mongo.db.partners.update_one(
                    {"_id": ObjectId(old_supplier_id_str)},
                    {"$pull": {"connections": package_oid}}
                )
            except:
                pass 
        
        # Add package to new supplier's connections
        if new_supplier_id_str:
            try:
                mongo.db.partners.update_one(
                    {"_id": ObjectId(new_supplier_id_str)},
                    {"$addToSet": {"connections": package_oid}}
                )
            except:
                pass

        _log_activity("connection_update", f"Updated supplier for packaging: {package.get('package_code', 'N/A')}")
        flash("Supplier linked successfully!", "success")

    except Exception as e:
        flash(f"An error occurred: {str(e)}", "danger")
    
    # Redirect based on referer
    referer = request.headers.get('Referer', '')
    if '/dashboard' in referer:
        return redirect(url_for("main.dashboard"))
    return redirect(url_for("main.products"))


@main_bp.route("/update_partner_connections/<partner_id>", methods=["POST"])
@login_required
def update_partner_connections(partner_id):
    try:
        partner_oid = ObjectId(partner_id)
        owner_oid = ObjectId(current_user.id)
        
        partner = mongo.db.partners.find_one({"_id": partner_oid, "owner": owner_oid})
        if not partner:
            flash("Partner not found.", "danger")
            return redirect(url_for("main.products"))

        new_linked_ids_str = request.form.getlist("linked_item_ids")
        new_linked_oids = {ObjectId(id_str) for id_str in new_linked_ids_str}

        old_connection_ids = partner.get("connections", [])
        old_linked_oids = {ObjectId(c) for c in old_connection_ids if c}

        ids_to_unlink = old_linked_oids - new_linked_oids
        ids_to_link = new_linked_oids - old_linked_oids

        partner_type = partner.get("partner_type", "").lower()

        if partner_type == "customer":
            if ids_to_unlink:
                mongo.db.products.update_many(
                    {"_id": {"$in": list(ids_to_unlink)}},
                    {"$set": {"connections.customer": ""}}
                )
            if ids_to_link:
                mongo.db.products.update_many(
                    {"_id": {"$in": list(ids_to_link)}},
                    {"$set": {"connections.customer": partner_id}}
                )
        elif partner_type == "supplier":
            pkg_collections = [mongo.db.primary_packagings, mongo.db.secondary_packagings, mongo.db.tertiary_packagings]
            if ids_to_unlink:
                for coll in pkg_collections:
                    coll.update_many({"_id": {"$in": list(ids_to_unlink)}}, {"$set": {"supplier": ""}})
            if ids_to_link:
                for coll in pkg_collections:
                    # This is inefficient, but necessary with the current schema
                    coll.update_many({"_id": {"$in": list(ids_to_link)}}, {"$set": {"supplier": partner_id}})

        # Update the partner's own connection list
        mongo.db.partners.update_one(
            {"_id": partner_oid},
            {"$set": {"connections": list(new_linked_oids)}}
        )

        _log_activity("connection_update", f"Updated connections for partner: {partner['partner_name']}")
        flash("Partner connections updated successfully!", "success")

    except Exception as e:
        flash(f"An error occurred: {str(e)}", "danger")

    return redirect(url_for("main.products"))


def get_activity_icon(activity_type):
    """Returns a Bootstrap icon class based on the activity type."""
    if not isinstance(activity_type, str):
        return "bi-info-circle"

    if "product_creation" == activity_type:
        return "bi-plus-square"
    if "product_update" == activity_type:
        return "bi-pencil-square"
    if "product_deletion" == activity_type:
        return "bi-trash"
        
    if "packaging_creation" == activity_type:
        return "bi-box-seam"
    if "packaging_update" == activity_type:
        return "bi-pencil-square"
    if "packaging_deletion" == activity_type:
        return "bi-trash"

    if "partner_creation" == activity_type:
        return "bi-person-plus"
    if "partner_update" == activity_type:
        return "bi-pencil-square"
    if "partner_deletion" == activity_type:
        return "bi-person-dash"

    if "connection" in activity_type:
        return "bi-link-45deg"
    if "sales" in activity_type:
        return "bi-graph-up-arrow"

    # Fallback for general types
    if "product" in activity_type:
        return "bi-qr-code"
    elif "packaging" in activity_type:
        return "bi-box"
    elif "partner" in activity_type:
        return "bi-person"
        
    return "bi-info-circle"


@main_bp.get("/dashboard")
@login_required
def dashboard():
    owner_id = ObjectId(current_user.id)

    # --- Filter Processing ---
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")
    product_ids = request.args.getlist("product_ids")
    packaging_levels = request.args.getlist("packaging_levels")

    if "packaging_levels" not in request.args:
        # On initial load, consider all levels to be selected.
        packaging_levels = ["Primary", "Secondary", "Tertiary"]

    start_date, end_date = None, None
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m")
        except ValueError:
            start_date = None
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, "%Y-%m")
        except ValueError:
            end_date = None

    # --- Data Fetching ---
    product_filter = {"owner": owner_id}
    if product_ids:
        product_filter["_id"] = {"$in": [ObjectId(pid) for pid in product_ids]}

    all_products = list(mongo.db.products.find(
        product_filter,
        {"product_code": 1, "sales": 1, "connections": 1}
    ))

    package_collections = {
        "Primary": mongo.db.primary_packagings,
        "Secondary": mongo.db.secondary_packagings,
        "Tertiary": mongo.db.tertiary_packagings,
    }

    all_packages = {}
    for level, collection in package_collections.items():
        for pkg in collection.find({"owner": owner_id}):
            pkg["level"] = level
            all_packages[str(pkg.get("_id"))] = pkg

    # --- Helper Functions ---
    def _package_unit_weight(pkg_doc):
        """Calculates the total weight of a single packaging unit in grams."""
        return sum(_safe_float(m.get("weight_grams")) or 0 for m in pkg_doc.get("materials", []))

    # --- Aggregation ---
    packaging_qty_by_grade = {"A": 0, "B": 0, "C": 0, "D": 0}
    packaging_weight_by_grade = {"A": 0.0, "B": 0.0, "C": 0.0, "D": 0.0}
    packaging_trend = {} # "YYYY-MM" -> {"A": 0, "B": 0, ...}

    for product in all_products:
        connections = product.get("connections", {})
        pkg_ids = [
            connections.get("primary_package"),
            connections.get("secondary_package"),
            connections.get("tertiary_package")
        ]
        pkg_docs = [all_packages.get(pkg_id) for pkg_id in pkg_ids]

        qty_primary_in_secondary = pkg_docs[1].get("quantity_primary_in_secondary_unit", 1) if pkg_docs[1] else 1
        qty_secondary_in_tertiary = pkg_docs[2].get("quantity_secondary_in_tertiary_unit", 1) if pkg_docs[2] else 1

        for sale in product.get("sales", []):
            try:
                sale_year = int(sale["year"])
                sale_month = int(sale["month"])
                sale_date = datetime(sale_year, sale_month, 1)
                
                is_after_start = not start_date or sale_date >= start_date
                is_before_end = not end_date or sale_date <= end_date

                if is_after_start and is_before_end:
                    quantity = _safe_float(sale.get("quantity")) or 0
                    if quantity == 0:
                        continue
                    
                    # --- Calculate units for this sale ---
                    total_primary_units = quantity
                    total_secondary_units = math.ceil(total_primary_units / qty_primary_in_secondary) if qty_primary_in_secondary > 0 else 0
                    total_tertiary_units = math.ceil(total_secondary_units / qty_secondary_in_tertiary) if qty_secondary_in_tertiary > 0 else 0
                    num_units_per_level = [total_primary_units, total_secondary_units, total_tertiary_units]

                    # --- Trend Data ---
                    sale_label = f"{sale_year}-{sale_month:02d}"
                    if sale_label not in packaging_trend:
                        packaging_trend[sale_label] = {"A": 0, "B": 0, "C": 0, "D": 0}

                    # --- Aggregate data ---
                    for i, pkg_doc in enumerate(pkg_docs):
                        num_units = num_units_per_level[i]
                        if not pkg_doc or num_units == 0:
                            continue

                        # Filter by packaging level
                        level = pkg_doc.get("level")
                        if level not in packaging_levels:
                            continue

                        grade = (str(pkg_doc.get("recyclability") or "N/A")).strip().upper()
                        if grade not in packaging_qty_by_grade:
                            continue
                        
                        # Pie chart totals
                        packaging_qty_by_grade[grade] += num_units
                        unit_weight = _package_unit_weight(pkg_doc)
                        packaging_weight_by_grade[grade] += unit_weight * num_units
                        
                        # Trend data
                        packaging_trend[sale_label][grade] += num_units

            except (ValueError, TypeError):
                continue

    # --- Final Data Preparation ---
    packaging_weight_kg_by_grade = {k: round(v / 1000, 2) for k, v in packaging_weight_by_grade.items()}
    
    # Sort trend data by date
    sorted_trend_labels = sorted(packaging_trend.keys())
    sorted_packaging_trend = {label: packaging_trend[label] for label in sorted_trend_labels}

    user_products = list(mongo.db.products.find({'owner': owner_id}, {"product_code": 1, "_id": 1}))

    # --- Fetch Latest Activities ---
    latest_activities = list(mongo.db.activities.find(
        {"owner": owner_id}
    ).sort("timestamp", -1).limit(10))

    # --- Fetch data for edit modals ---
    all_primary_packagings = list(mongo.db.primary_packagings.find({"owner": owner_id}))
    all_secondary_packagings = list(mongo.db.secondary_packagings.find({"owner": owner_id}))
    all_tertiary_packagings = list(mongo.db.tertiary_packagings.find({"owner": owner_id}))
    partners = list(mongo.db.partners.find({"owner": owner_id}))
    # For editLinkedProductsModal, we need all products (use user_products as products)
    products = user_products
    
    # Fetch data setup items for packaging modals
    component_types = list(mongo.db.component_types.find({"owner": owner_id}).sort("name", 1))
    adhesives = list(mongo.db.adhesives.find({"owner": owner_id}).sort("name", 1))
    food_contacts = list(mongo.db.food_contacts.find({"owner": owner_id}).sort("name", 1))
    coatings = list(mongo.db.coatings.find({"owner": owner_id}).sort("name", 1))

    return render_template(
        'dashboard_page.html',
        packaging_qty_by_grade=packaging_qty_by_grade,
        packaging_weight_by_grade=packaging_weight_kg_by_grade,
        packaging_trend=sorted_packaging_trend,
        products=products,  # For both filter and edit modals
        start_date=start_date_str,
        end_date=end_date_str,
        datetime=datetime,
        request=request,
        latest_activities=latest_activities,
        get_activity_icon=get_activity_icon,
        # For edit modals
        all_primary_packagings=all_primary_packagings,
        all_secondary_packagings=all_secondary_packagings,
        all_tertiary_packagings=all_tertiary_packagings,
        partners=partners,
        component_types=component_types,
        adhesives=adhesives,
        food_contacts=food_contacts,
        coatings=coatings
    )



@main_bp.get("/partners")
@login_required
def partners():
    return render_template("dashboard_page.html")

@main_bp.get("/compliance")
@login_required
def compliance():
    return render_template("dashboard_page.html")

@main_bp.get("/reports")
@login_required
def reports():
    return render_template("dashboard_page.html")

@main_bp.get("/data-setup")
@login_required
def data_setup():
    owner_id = ObjectId(current_user.id)
    
    # Fetch all items for each list
    component_types = list(mongo.db.component_types.find({"owner": owner_id}).sort("name", 1))
    adhesives = list(mongo.db.adhesives.find({"owner": owner_id}).sort("name", 1))
    food_contacts = list(mongo.db.food_contacts.find({"owner": owner_id}).sort("name", 1))
    coatings = list(mongo.db.coatings.find({"owner": owner_id}).sort("name", 1))
    
    return render_template(
        "data_setup_page.html",
        component_types=component_types,
        adhesives=adhesives,
        food_contacts=food_contacts,
        coatings=coatings
    )


@main_bp.route("/add_data_setup_item", methods=["POST"])
@login_required
def add_data_setup_item():
    try:
        owner_id = ObjectId(current_user.id)
        item_type = request.form.get("type")
        name = request.form.get("name", "").strip()
        
        if not name:
            return jsonify({"status": "error", "message": "Name is required"}), 400
        
        # Determine collection based on type
        collection_map = {
            "component_type": mongo.db.component_types,
            "adhesive": mongo.db.adhesives,
            "food_contact": mongo.db.food_contacts,
            "coating": mongo.db.coatings
        }
        
        if item_type not in collection_map:
            return jsonify({"status": "error", "message": "Invalid item type"}), 400
        
        collection = collection_map[item_type]
        
        # Check if name already exists for this owner
        existing = collection.find_one({"owner": owner_id, "name": name})
        if existing:
            return jsonify({"status": "error", "message": "This name already exists"}), 400
        
        # Insert new item
        result = collection.insert_one({
            "owner": owner_id,
            "name": name,
            "created_at": datetime.now(timezone.utc)
        })
        
        return jsonify({
            "status": "success",
            "item_id": str(result.inserted_id),
            "message": "Item added successfully"
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@main_bp.route("/update_data_setup_item", methods=["POST"])
@login_required
def update_data_setup_item():
    try:
        owner_id = ObjectId(current_user.id)
        item_id = request.form.get("item_id")
        item_type = request.form.get("type")
        name = request.form.get("name", "").strip()
        
        if not name:
            return jsonify({"status": "error", "message": "Name is required"}), 400
        
        if not item_id:
            return jsonify({"status": "error", "message": "Item ID is required"}), 400
        
        # Determine collection based on type
        collection_map = {
            "component_type": mongo.db.component_types,
            "adhesive": mongo.db.adhesives,
            "food_contact": mongo.db.food_contacts,
            "coating": mongo.db.coatings
        }
        
        if item_type not in collection_map:
            return jsonify({"status": "error", "message": "Invalid item type"}), 400
        
        collection = collection_map[item_type]
        item_oid = ObjectId(item_id)
        
        # Verify ownership
        item = collection.find_one({"_id": item_oid, "owner": owner_id})
        if not item:
            return jsonify({"status": "error", "message": "Item not found or access denied"}), 404
        
        # Check if name already exists for this owner (excluding current item)
        existing = collection.find_one({
            "owner": owner_id,
            "name": name,
            "_id": {"$ne": item_oid}
        })
        if existing:
            return jsonify({"status": "error", "message": "This name already exists"}), 400
        
        # Update item
        collection.update_one(
            {"_id": item_oid, "owner": owner_id},
            {"$set": {"name": name, "updated_at": datetime.now(timezone.utc)}}
        )
        
        return jsonify({
            "status": "success",
            "message": "Item updated successfully"
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@main_bp.route("/delete_data_setup_item", methods=["POST"])
@login_required
def delete_data_setup_item():
    try:
        owner_id = ObjectId(current_user.id)
        item_id = request.form.get("item_id")
        item_type = request.form.get("type")
        
        if not item_id:
            return jsonify({"status": "error", "message": "Item ID is required"}), 400
        
        # Determine collection based on type
        collection_map = {
            "component_type": mongo.db.component_types,
            "adhesive": mongo.db.adhesives,
            "food_contact": mongo.db.food_contacts,
            "coating": mongo.db.coatings
        }
        
        if item_type not in collection_map:
            return jsonify({"status": "error", "message": "Invalid item type"}), 400
        
        collection = collection_map[item_type]
        item_oid = ObjectId(item_id)
        
        # Verify ownership and delete
        result = collection.delete_one({"_id": item_oid, "owner": owner_id})
        
        if result.deleted_count == 0:
            return jsonify({"status": "error", "message": "Item not found or access denied"}), 404
        
        return jsonify({
            "status": "success",
            "message": "Item deleted successfully"
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@main_bp.get("/settings")
@login_required
def settings():
    return render_template("dashboard_page.html")

@main_bp.get("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.login"))


@main_bp.route("/delete_product/<product_id>", methods=["POST"])
@login_required
def delete_product(product_id):
    try:
        product_oid = ObjectId(product_id)
        owner_oid = ObjectId(current_user.id)

        # 1. Find the product to ensure it exists and belongs to the user
        product = mongo.db.products.find_one({"_id": product_oid, "owner": owner_oid})
        if not product:
            return jsonify({"status": "error", "message": "Product not found or access denied"}), 404

        product_code = product.get("product_code", "N/A")
        connections = product.get("connections", {})

        # 2. Unlink from packaging collections
        pkg_collections = {
            "primary_package": mongo.db.primary_packagings,
            "secondary_package": mongo.db.secondary_packagings,
            "tertiary_package": mongo.db.tertiary_packagings
        }
        for level_key, collection in pkg_collections.items():
            pkg_id_str = connections.get(level_key)
            if pkg_id_str:
                try:
                    # Remove the product's reference from the package's `connections` array.
                    # This now correctly targets the dictionary entry by the product's stringified ObjectId.
                    collection.update_one(
                        {"_id": ObjectId(pkg_id_str)},
                        {"$pull": {"connections": {"_id": str(product_oid)}}}
                    )
                except Exception as e:
                    print(f"Could not unlink product from {level_key} ({pkg_id_str}): {e}")

        # 3. Unlink from partner (customer)
        customer_id_str = connections.get("customer")
        if customer_id_str:
            try:
                # Remove the product's ObjectId from the partner's `connections` array.
                mongo.db.partners.update_one(
                    {"_id": ObjectId(customer_id_str)},
                    {"$pull": {"connections": product_oid}}
                )
            except Exception as e:
                print(f"Could not unlink product from customer ({customer_id_str}): {e}")


        # 4. Delete the product itself
        mongo.db.products.delete_one({"_id": product_oid})
        
        _log_activity("product_deletion", f"Deleted product: {product_code}")

        return jsonify({"status": "success", "message": f"Product '{product_code}' deleted successfully."})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500








@main_bp.get("/get_product_details/<product_id>")
@login_required
def get_product_details(product_id):
    try:
        product_oid = ObjectId(product_id)
        owner_oid = ObjectId(current_user.id)

        product = mongo.db.products.find_one({
            "_id": product_oid,
            "owner": owner_oid
        })

        if not product:
            return jsonify({"error": "Product not found"}), 404

        # Convert ObjectId to string for JSON serialization
        product["_id"] = str(product["_id"])
        product["owner"] = str(product["owner"])

        connections = product.get("connections", {})
        
        # Fetch details for connected items
        packaging_details = []
        
        primary_pkg_id = connections.get("primary_package")
        if primary_pkg_id:
            try:
                pkg = mongo.db.primary_packagings.find_one({"_id": ObjectId(primary_pkg_id)}, {"package_code": 1, "recyclability": 1})
                if pkg:
                    packaging_details.append({
                        "code": pkg.get("package_code", "Not Found"),
                        "level": "Primary",
                        "recyclability": pkg.get("recyclability", "N/A")
                    })
            except:
                pass # Invalid ID

        secondary_pkg_id = connections.get("secondary_package")
        if secondary_pkg_id:
            try:
                pkg = mongo.db.secondary_packagings.find_one({"_id": ObjectId(secondary_pkg_id)}, {"package_code": 1, "recyclability": 1})
                if pkg:
                    packaging_details.append({
                        "code": pkg.get("package_code", "Not Found"),
                        "level": "Secondary",
                        "recyclability": pkg.get("recyclability", "N/A")
                    })
            except:
                pass # Invalid ID

        tertiary_pkg_id = connections.get("tertiary_package")
        if tertiary_pkg_id:
            try:
                pkg = mongo.db.tertiary_packagings.find_one({"_id": ObjectId(tertiary_pkg_id)}, {"package_code": 1, "recyclability": 1})
                if pkg:
                    packaging_details.append({
                        "code": pkg.get("package_code", "Not Found"),
                        "level": "Tertiary",
                        "recyclability": pkg.get("recyclability", "N/A")
                    })
            except:
                pass # Invalid ID

        connections['packaging'] = packaging_details
        # Clean up old keys if they exist
        connections.pop("primary_package_name", None)
        connections.pop("secondary_package_name", None)
        connections.pop("tertiary_package_name", None)

        customer_id = connections.get("customer")
        if customer_id:
            try:
                customer = mongo.db.partners.find_one({"_id": ObjectId(customer_id)}, {"partner_name": 1})
                connections["customer_name"] = customer.get("partner_name") if customer else "Not Found"
            except:
                connections["customer_name"] = "Invalid ID"


        product["connections"] = connections

        # Clean up non-serializable fields if they are not needed by the frontend
        if 'creation_time' in product:
            product.pop('creation_time')

        return jsonify(product)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@main_bp.get("/get_packaging_details")
@login_required
def get_packaging_details():
    try:
        package_id = request.args.get('id')
        level = request.args.get('level')
        # A new flag to determine the response format
        is_for_editing = request.args.get('edit', 'false').lower() == 'true'
        owner_oid = ObjectId(current_user.id)

        collection = None
        if level == 'Primary':
            collection = mongo.db.primary_packagings
        elif level == 'Secondary':
            collection = mongo.db.secondary_packagings
        elif level == 'Tertiary':
            collection = mongo.db.tertiary_packagings
        
        if collection is None:
            return jsonify({"error": "Invalid packaging level"}), 400

        package = collection.find_one({"_id": ObjectId(package_id), "owner": owner_oid})

        if not package:
            return jsonify({"error": "Packaging not found"}), 404

        # If for editing, return the full document
        if is_for_editing:
            package["_id"] = str(package["_id"])
            package["owner"] = str(package["owner"])
            if 'creation_time' in package:
                package.pop('creation_time')
            return jsonify(package)

        # --- Otherwise, return the summarized version for the offcanvas ---
        
        # Get linked products
        linked_products_raw = package.get("connections", [])
        clean_linked_products = []
        product_ids_to_fetch = []

        for item in linked_products_raw:
            if isinstance(item, dict) and 'product_code' in item:
                clean_linked_products.append(item)
            elif isinstance(item, ObjectId):
                product_ids_to_fetch.append(item)
            elif isinstance(item, dict) and '$oid' in item:
                try:
                    product_ids_to_fetch.append(ObjectId(item['$oid']))
                except:
                    pass

        if product_ids_to_fetch:
            products_cursor = mongo.db.products.find(
                {"_id": {"$in": product_ids_to_fetch}},
                {"product_code": 1}
            )
            for p in products_cursor:
                clean_linked_products.append({
                    '_id': str(p['_id']),
                    'product_code': p['product_code']
                })

        # Get linked supplier
        supplier_name = "Not linked"
        if "supplier" in package and package["supplier"]:
            try:
                supplier = mongo.db.partners.find_one(
                    {"_id": ObjectId(package["supplier"])},
                    {"partner_name": 1}
                )
                if supplier:
                    supplier_name = supplier.get("partner_name")
            except:
                supplier_name = "Invalid Supplier ID"

        result = {
            "_id": str(package["_id"]),
            "package_code": package.get("package_code"),
            "level": level,
            "component_type": pick_component_type_text(package),
            "material": pick_material_text(package),
            "recyclability": package.get("recyclability") or "—",
            "linked_products": clean_linked_products,
            "supplier_id": str(package.get("supplier")),
            "supplier_name": supplier_name
        }

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@main_bp.get("/get_product_sales/<product_id>")
@login_required
def get_product_sales(product_id):
    product = mongo.db.products.find_one({
        "_id": ObjectId(product_id),
        "owner": ObjectId(current_user.id)
    }, {"sales": 1, "product_code": 1})

    if not product:
        return jsonify({"sales": []})

    return jsonify({"sales": product.get("sales", [])})


@main_bp.get("/get_activities")
@login_required
def get_activities():
    owner_id = ObjectId(current_user.id)
    activities = list(mongo.db.activities.find(
        {"owner": owner_id}
    ).sort("timestamp", -1).limit(100))
    
    # Convert ObjectId and datetime to string for JSON serialization
    for activity in activities:
        activity["_id"] = str(activity["_id"])
        activity["timestamp"] = activity["timestamp"].isoformat()

    return jsonify(activities)


@main_bp.post("/add_product_sales/<product_id>")
@login_required
def add_product_sales(product_id):
    data = request.get_json(silent=True) or {}

    year = data.get("year")
    month = data.get("month")
    quantity = data.get("quantity")

    if not all([year, month, quantity]):
        return jsonify({"status": "error", "message": "Year, Month, and Quantity are required"}), 400

    product = mongo.db.products.find_one({
        "_id": ObjectId(product_id),
        "owner": ObjectId(current_user.id)
    }, {"_id": 1, "product_code": 1})

    if not product:
        return jsonify({"status": "error", "message": "Product not found"}), 404

    new_record = {
        "year": year,
        "month": month,
        "quantity": quantity,
        "sku_price": data.get("sku_price")  # Optional
    }

    mongo.db.products.update_one(
        {"_id": ObjectId(product_id)},
        {"$push": {"sales": new_record}}
    )

    _log_activity("sales_addition", f"Added {month}/{year} sales to product: {product.get('product_code')}")

    return jsonify({"status": "success"})


@main_bp.post("/update_product_sales/<product_id>/<int:index>")
@login_required
def update_product_sales(product_id, index):
    data = request.get_json(silent=True) or {}

    product = mongo.db.products.find_one({
        "_id": ObjectId(product_id),
        "owner": ObjectId(current_user.id)
    }, {"sales": 1})

    if not product:
        return jsonify({"status": "error", "message": "Product not found"}), 404

    sales = product.get("sales", []) or []
    if index < 0 or index >= len(sales):
        return jsonify({"status": "error", "message": "Invalid sale index"}), 400

    fields = {}
    if "year" in data:
        fields[f"sales.{index}.year"] = data.get("year")
    if "month" in data:
        fields[f"sales.{index}.month"] = data.get("month")
    if "quantity" in data:
        fields[f"sales.{index}.quantity"] = data.get("quantity")
    if "sku_price" in data:
        fields[f"sales.{index}.sku_price"] = data.get("sku_price")

    if not fields:
        return jsonify({"status": "error", "message": "No fields to update"}), 400

    mongo.db.products.update_one(
        {"_id": ObjectId(product_id), "owner": ObjectId(current_user.id)},
        {"$set": fields}
    )

    return jsonify({"status": "success"})


@main_bp.post("/delete_product_sales/<product_id>/<int:index>")
@login_required
def delete_product_sales(product_id, index):
    product = mongo.db.products.find_one({
        "_id": ObjectId(product_id),
        "owner": ObjectId(current_user.id)
    }, {"sales": 1})

    if not product:
        return jsonify({"status": "error", "message": "Product not found"}), 404

    sales = product.get("sales", []) or []
    if index < 0 or index >= len(sales):
        return jsonify({"status": "error", "message": "Invalid sale index"}), 400

    sales.pop(index)

    mongo.db.products.update_one(
        {"_id": ObjectId(product_id), "owner": ObjectId(current_user.id)},
        {"$set": {"sales": sales}}
    )

    return jsonify({"status": "success"})


@main_bp.route("/delete_partner/<partner_id>", methods=["POST"])
@login_required
def delete_partner(partner_id):
    try:
        partner_oid = ObjectId(partner_id)
        owner_oid = ObjectId(current_user.id)

        # 1. Find the partner to ensure it exists and belongs to the user
        partner = mongo.db.partners.find_one({"_id": partner_oid, "owner": owner_oid})
        if not partner:
            return jsonify({"status": "error", "message": "Partner not found or access denied"}), 404

        partner_name = partner.get("partner_name", "N/A")
        
        # 2. Unlink from products (customers)
        mongo.db.products.update_many(
            {"owner": owner_oid, "connections.customer": partner_id},
            {"$set": {"connections.customer": ""}}
        )

        # 3. Unlink from packaging (suppliers)
        # This requires checking all three packaging collections
        pkg_collections = [
            mongo.db.primary_packagings,
            mongo.db.secondary_packagings,
            mongo.db.tertiary_packagings
        ]
        for collection in pkg_collections:
            collection.update_many(
                {"owner": owner_oid, "supplier": partner_id},
                {"$set": {"supplier": ""}}
            )

        # 4. Delete the partner itself
        mongo.db.partners.delete_one({"_id": partner_oid})
        
        _log_activity("partner_deletion", f"Deleted partner: {partner_name}")

        return jsonify({"status": "success", "message": f"Partner '{partner_name}' deleted successfully."})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@main_bp.route("/delete_packaging/<package_id>", methods=["POST"])
@login_required
def delete_packaging(package_id):
    try:
        package_oid = ObjectId(package_id)
        level = request.args.get('level')
        owner_oid = ObjectId(current_user.id)

        collections = {
            "Primary": mongo.db.primary_packagings,
            "Secondary": mongo.db.secondary_packagings,
            "Tertiary": mongo.db.tertiary_packagings
        }
        collection = collections.get(level)
        connection_field = f"connections.{level.lower()}_package"

        if collection is None:
            return jsonify({"status": "error", "message": "Invalid packaging level"}), 400

        # 1. Find the packaging to ensure it exists and belongs to the user
        package = collection.find_one({"_id": package_oid, "owner": owner_oid})
        if not package:
            return jsonify({"status": "error", "message": "Packaging not found or access denied"}), 404

        package_code = package.get("package_code", "N/A")

        # 2. Unlink from products
        mongo.db.products.update_many(
            {"owner": owner_oid, connection_field: package_id},
            {"$set": {connection_field: ""}}
        )

        # 3. Delete the packaging itself
        collection.delete_one({"_id": package_oid})
        
        _log_activity("packaging_deletion", f"Deleted {level} packaging: {package_code}")

        return jsonify({"status": "success", "message": f"Packaging '{package_code}' deleted successfully."})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@main_bp.route('/get_recyclability_form/<form_name>')
@login_required
def get_recyclability_form(form_name):
    """
    Renders a specific recyclability form template.
    Note: This is an authenticated route.
    """
    try:
        # Basic security: prevent directory traversal
        if '..' in form_name or '/' in form_name:
            return "Invalid form name", 400
        
        template_path = f"recyclability_forms/{form_name}"
        
        # render_template will raise a TemplateNotFound error if the file doesn't exist,
        # which will be caught by the generic exception handler below.
        return render_template(template_path)

    except Exception as e:
        # In a real app, you might want more specific error handling
        # and logging for template not found errors.
        return f"Form '{form_name}' not found.", 404


@main_bp.route("/update_packaging_recyclability", methods=["POST"])
@login_required
def update_packaging_recyclability():
    """
    Updates only the recyclability field of a packaging item.
    """
    try:
        package_id_str = request.form.get('packageId')
        package_level = request.form.get('packageLevel')
        recyclability = request.form.get('recyclability')
        
        if not all([package_id_str, package_level, recyclability]):
            return jsonify({"status": "error", "message": "Missing required fields"}), 400
        
        package_oid = ObjectId(package_id_str)
        owner_oid = ObjectId(current_user.id)
        
        collections = {
            "Primary": mongo.db.primary_packagings,
            "Secondary": mongo.db.secondary_packagings,
            "Tertiary": mongo.db.tertiary_packagings
        }
        collection = collections.get(package_level)
        
        if collection is None:
            return jsonify({"status": "error", "message": "Invalid packaging level"}), 400
        
        # Verify ownership
        package = collection.find_one({"_id": package_oid, "owner": owner_oid})
        if not package:
            return jsonify({"status": "error", "message": "Packaging not found or access denied"}), 404
        
        # Update only recyclability
        collection.update_one(
            {"_id": package_oid},
            {"$set": {"recyclability": recyclability}}
        )
        
        _log_activity("packaging_update", f"Updated recyclability for {package_level} packaging: {package.get('package_code', 'N/A')}")
        
        return jsonify({"status": "success", "message": "Recyclability updated successfully"})
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@main_bp.get("/get_all_products_json")
@login_required
def get_all_products_json():
    owner_oid = ObjectId(current_user.id)
    products = list(mongo.db.products.find({"owner": owner_oid}, {"_id": 1, "product_code": 1}))
    for p in products:
        p["_id"] = str(p["_id"])
    return jsonify(products)

@main_bp.get("/get_all_packagings_json")
@login_required
def get_all_packagings_json():
    owner_oid = ObjectId(current_user.id)
    all_packagings = []
    pkg_collections = {
        "Primary": mongo.db.primary_packagings,
        "Secondary": mongo.db.secondary_packagings,
        "Tertiary": mongo.db.tertiary_packagings
    }
    for level, collection in pkg_collections.items():
        packagings = list(collection.find({"owner": owner_oid}, {"_id": 1, "package_code": 1}))
        for p in packagings:
            p["_id"] = str(p["_id"])
            p["level"] = level
            all_packagings.append(p)
    return jsonify(all_packagings)

@main_bp.get("/get_missing_recyclability")
@login_required
def get_missing_recyclability():
    """
    Returns list of packagings that don't have recyclability set.
    """
    try:
        owner_oid = ObjectId(current_user.id)
        
        missing_recyclability = []
        
        # Check all packaging levels
        collections = {
            "Primary": mongo.db.primary_packagings,
            "Secondary": mongo.db.secondary_packagings,
            "Tertiary": mongo.db.tertiary_packagings
        }
        
        for level, collection in collections.items():
            packagings = collection.find(
                {"owner": owner_oid},
                {"package_code": 1, "recyclability": 1, "materials": 1}
            )
            
            for pkg in packagings:
                recyclability = pkg.get("recyclability")
                # Check if recyclability is missing, empty, or not a valid grade
                if not recyclability or recyclability.strip() == "" or recyclability == "—":
                    # Get material for the recyclability form
                    material = pick_material_text(pkg)
                    
                    missing_recyclability.append({
                        "_id": str(pkg["_id"]),
                        "package_code": pkg.get("package_code", "N/A"),
                        "level": level,
                        "material": material
                    })
        
        return jsonify({
            "count": len(missing_recyclability),
            "packagings": missing_recyclability
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@main_bp.get("/get_product_status")
@login_required
def get_product_status():
    """
    Returns product status statistics including missing connections.
    """
    try:
        owner_oid = ObjectId(current_user.id)
        
        # Get all products
        all_products = list(mongo.db.products.find(
            {"owner": owner_oid},
            {"product_code": 1, "connections": 1}
        ))
        
        # Get all packagings
        all_primary = list(mongo.db.primary_packagings.find({"owner": owner_oid}, {"package_code": 1, "supplier": 1}))
        all_secondary = list(mongo.db.secondary_packagings.find({"owner": owner_oid}, {"package_code": 1, "supplier": 1}))
        all_tertiary = list(mongo.db.tertiary_packagings.find({"owner": owner_oid}, {"package_code": 1, "supplier": 1}))
        all_packagings = all_primary + all_secondary + all_tertiary
        
        # Analyze products
        missing_primary = []
        missing_secondary = []
        missing_tertiary = []
        missing_customer = []
        
        for product in all_products:
            connections = product.get("connections", {})
            product_info = {
                "_id": str(product["_id"]),
                "product_code": product.get("product_code", "N/A")
            }
            
            if not connections.get("primary_package"):
                missing_primary.append(product_info)
            if not connections.get("secondary_package"):
                missing_secondary.append(product_info)
            if not connections.get("tertiary_package"):
                missing_tertiary.append(product_info)
            if not connections.get("customer"):
                missing_customer.append(product_info)
        
        # Analyze packagings missing supplier
        missing_supplier = []
        for pkg in all_packagings:
            if not pkg.get("supplier"):
                missing_supplier.append({
                    "_id": str(pkg["_id"]),
                    "package_code": pkg.get("package_code", "N/A")
                })
        
        # Calculate totals
        total_at_risk = len(set(
            [p["_id"] for p in missing_primary] +
            [p["_id"] for p in missing_secondary] +
            [p["_id"] for p in missing_tertiary] +
            [p["_id"] for p in missing_customer]
        ))
        
        total_incomplete = total_at_risk  # Same for now
        total_compliant = len(all_products) - total_at_risk
        
        return jsonify({
            "summary": {
                "at_risk": total_at_risk,
                "incomplete": total_incomplete,
                "compliant": total_compliant
            },
            "missing_primary": {
                "count": len(missing_primary),
                "products": missing_primary
            },
            "missing_secondary": {
                "count": len(missing_secondary),
                "products": missing_secondary
            },
            "missing_tertiary": {
                "count": len(missing_tertiary),
                "products": missing_tertiary
            },
            "missing_customer": {
                "count": len(missing_customer),
                "products": missing_customer
            },
            "missing_supplier": {
                "count": len(missing_supplier),
                "packagings": missing_supplier
            }
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@main_bp.get("/get_partner_details/<partner_id>")
@login_required
def get_partner_details(partner_id):
    try:
        partner_oid = ObjectId(partner_id)
        owner_oid = ObjectId(current_user.id)

        partner = mongo.db.partners.find_one({
            "_id": partner_oid,
            "owner": owner_oid
        })

        if not partner:
            return jsonify({"error": "Partner not found"}), 404

        partner_type = partner.get("partner_type", "").lower()
        connected_items = []
        connection_ids = partner.get("connections", [])

        if connection_ids:
            # Ensure all connection_ids are ObjectIds
            connection_oids = [ObjectId(c) for c in connection_ids if c]

            if partner_type == "customer":
                products = mongo.db.products.find(
                    {"_id": {"$in": connection_oids}},
                    {"product_code": 1}
                )
                for p in products:
                    connected_items.append({
                        "_id": str(p["_id"]),
                        "code": p.get("product_code", "N/A"),
                        "type": "Product"
                    })
            elif partner_type == "supplier":
                pkg_collections = {
                    "Primary": mongo.db.primary_packagings,
                    "Secondary": mongo.db.secondary_packagings,
                    "Tertiary": mongo.db.tertiary_packagings
                }
                for level, collection in pkg_collections.items():
                    packagings = collection.find(
                        {"_id": {"$in": connection_oids}},
                        {"package_code": 1}
                    )
                    for pkg in packagings:
                        connected_items.append({
                            "_id": str(pkg["_id"]),
                            "code": pkg.get("package_code", "N/A"),
                            "type": "Packaging",
                            "level": level
                        })
        
        partner["connections_detailed"] = connected_items

        # Convert ObjectId to string for JSON serialization
        partner["_id"] = str(partner["_id"])
        partner["owner"] = str(partner["owner"])
        if 'creation_time' in partner:
            partner.pop('creation_time')
        if 'connections' in partner:
            # We are sending connections_detailed instead
            partner.pop('connections')

        return jsonify(partner)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@main_bp.route("/update_partner/<partner_id>", methods=["POST"])
@login_required
def update_partner(partner_id):
    try:
        partner_oid = ObjectId(partner_id)
        owner_oid = ObjectId(current_user.id)

        partner = mongo.db.partners.find_one({"_id": partner_oid, "owner": owner_oid})
        if not partner:
            flash("Partner not found or access denied.", "danger")
            return redirect(url_for("main.products"))

        partner_name = request.form.get('partner_name')
        if not partner_name:
            flash('Partner Name is required.', 'danger')
            return redirect(url_for("main.products"))

        update_doc = {
            'partner_name': partner_name,
            'partner_type': request.form.get('partner_type'),
            'country': request.form.get('country'),
            'email': request.form.get('email'),
            'phone_number': request.form.get('phone_number'),
            'address': request.form.get('address'),
        }

        mongo.db.partners.update_one(
            {'_id': partner_oid},
            {'$set': update_doc}
        )

        _log_activity("partner_update", f"Updated partner: {partner_name}")
        flash(f'Partner "{partner_name}" has been updated successfully!', 'success')

    except Exception as e:
        flash(f'An error occurred while updating the partner: {str(e)}', 'danger')

    return redirect(url_for("main.products"))


@main_bp.route("/update_packaging/<package_id>", methods=["POST"])
@login_required
def update_packaging(package_id):
    try:
        package_oid = ObjectId(package_id)
        owner_oid = ObjectId(current_user.id)
        level = request.form.get('packagingLevel')
        
        collections = {
            "Primary": mongo.db.primary_packagings,
            "Secondary": mongo.db.secondary_packagings,
            "Tertiary": mongo.db.tertiary_packagings
        }
        collection = collections.get(level)
        if collection is None:
            flash(f'Invalid packaging level: {level}', 'danger')
            return redirect(url_for("main.products"))

        package = collection.find_one({"_id": package_oid, "owner": owner_oid})
        if not package:
            flash("Packaging not found or access denied.", "danger")
            return redirect(url_for("main.products"))

        # --- Basic Info ---
        package_code = request.form.get('packageCode')
        recyclability = request.form.get('recyclability')
        package_shape = request.form.get('packageShape')

        if not all([level, package_code]):
            flash('Level and Code are required.', 'danger')
            return redirect(url_for("main.products"))

        # --- Dimensions ---
        dimensions = {}
        if package_shape == 'rectangular':
            dimensions['length'] = request.form.get('length')
            dimensions['width'] = request.form.get('width')
            dimensions['height'] = request.form.get('height')
        elif package_shape == 'cylinder':
            dimensions['height'] = request.form.get('cylHeight')
            dimensions['radius'] = request.form.get('cylRadius')
        elif package_shape == 'sphere':
            dimensions['radius'] = request.form.get('sphRadius')
        elif package_shape == 'other':
            dimensions['volume'] = request.form.get('volume')
        
        # --- Material Composition ---
        components = request.form.getlist('packageComponent[]')
        materials = request.form.getlist('material[]')
        weights = request.form.getlist('weightGrams[]')
        recycled_contents = request.form.getlist('recycledContent[]')
        thicknesses = request.form.getlist('thicknessMicrons[]')
        adhesives = request.form.getlist('adhesiveType[]')
        food_contacts = request.form.getlist('foodContact[]')
        coatings = request.form.getlist('coatingType[]')

        materials_list = []
        for i in range(len(components)):
            if not components[i]: continue # Skip empty component rows
            materials_list.append({
                "package_component": components[i],
                "material": materials[i],
                "weight_grams": _safe_float(weights[i]),
                "recycled_content": _safe_float(recycled_contents[i]),
                "thickness_microns": _safe_float(thicknesses[i]),
                "adhesive_type": adhesives[i],
                "food_contact": food_contacts[i],
                "coating": coatings[i]
            })
            
        # --- Document Assembly for Update ---
        update_doc = {
            'package_code': package_code,
            'package_shape': package_shape,
            'dimensions': dimensions,
            'materials': materials_list,
            'recyclability': recyclability,
            'volume_cm3': calculate_volume(package_shape, dimensions),
        }
        
        if level == 'Secondary':
            update_doc['quantity_primary_in_secondary_unit'] = _safe_float(request.form.get('quantity_primary_in_secondary_unit'))
        elif level == 'Tertiary':
            update_doc['quantity_secondary_in_tertiary_unit'] = _safe_float(request.form.get('quantity_secondary_in_tertiary_unit'))
        
        collection.update_one(
            {'_id': package_oid},
            {'$set': update_doc}
        )

        _log_activity("packaging_update", f"Updated {level} packaging: {package_code}")
        flash(f'{level} packaging "{package_code}" has been updated successfully!', 'success')

    except Exception as e:
        flash(f'An error occurred: {str(e)}', 'danger')

    return redirect(url_for("main.products"))
