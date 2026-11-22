from kernel import plugins

# قاب جایگزین، نه محصول افزودنی بازارچه؛ مجوز قابلیت‌های واقعی جداگانه بررسی می‌شود.
plugins.register("live", "PostGIS Live", kind="system", requires=("maps",))
