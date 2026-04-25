def initialize_user(user_id, locale, currency):
    # Lấy categories với đúng locale, fallback về 'en' nếu không có
    sql = """
        SELECT
            mc.id        AS master_id,
            mc.icon,
            mc.type,
            mc.sort_order,
            COALESCE(
                (SELECT name FROM master_category_translations
                 WHERE category_id = mc.id AND locale = %s),
                (SELECT name FROM master_category_translations
                 WHERE category_id = mc.id AND locale = 'en')
            ) AS name
        FROM master_categories mc
        ORDER BY mc.sort_order
    """
    masters = db.query(sql, [locale])

    for m in masters:
        db.insert("categories", {
            "userid":    user_id,
            "name":      m.name,   # đã dịch đúng locale + fallback
            "icon":      m.icon,
            "type":      m.type,
            "sort_order": m.sort_order,
            "master_id": m.master_id
        })

    # ... tạo Cash wallet, tính MD5 như cũ