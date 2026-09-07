"""SQLite 상품·레시피 데이터를 장바구니에서 조회한다."""

from pathlib import Path
import sqlite3

PRODUCTS = [
    ("galic", "마늘", 1500), ("apple", "사과", 2000), ("l_onion", "대파", 1800),
    ("raw_pork", "돼지고기", 5000), ("onion", "양파", 2000), ("sliced_ham", "햄", 3000),
    ("carrot", "당근", 1500), ("egg", "계란", 4000), ("shrimp", "새우", 4500), ("bread", "식빵", 3500),
]
CLASS_NAME_ALIASES = {
    "green_onion": "l_onion",
    "green onion": "l_onion",
    "green-onion": "l_onion",
    "대파": "l_onion",
}
RECIPES = [
    ("대파새우전", "대파와 새우를 이용한 간단한 전"), ("사과토스트", "사과를 이용한 간단한 토스트"),
    ("계란찜", "계란과 대파를 이용한 간단한 계란찜"), ("제육볶음", "돼지고기와 채소를 이용한 제육볶음"),
    ("새우볶음밥", "새우와 채소, 계란을 이용한 볶음밥"),
]
RECIPE_INGREDIENTS = {
    "대파새우전": ["l_onion", "shrimp", "egg"], "사과토스트": ["apple", "bread", "egg"],
    "계란찜": ["egg", "l_onion"], "제육볶음": ["raw_pork", "onion", "l_onion", "galic", "carrot"],
    "새우볶음밥": ["shrimp", "egg", "l_onion", "carrot", "onion"],
}


class SmartCartDatabase:
    def __init__(self, db_path: str | Path = "smart_cart.db"):
        self.connection = sqlite3.connect(db_path)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.create_tables()
        self.insert_demo_data()

    def create_tables(self) -> None:
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS products (product_id INTEGER PRIMARY KEY AUTOINCREMENT, class_name TEXT NOT NULL UNIQUE, product_name TEXT NOT NULL, price INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS recipes (recipe_id INTEGER PRIMARY KEY AUTOINCREMENT, recipe_name TEXT NOT NULL UNIQUE, description TEXT);
            CREATE TABLE IF NOT EXISTS recipe_ingredients (recipe_id INTEGER NOT NULL, product_id INTEGER NOT NULL, PRIMARY KEY (recipe_id, product_id), FOREIGN KEY (recipe_id) REFERENCES recipes(recipe_id) ON DELETE CASCADE, FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE CASCADE);
        """)
        self.connection.commit()

    def insert_demo_data(self) -> None:
        for old_name, new_name in {"garlic": "galic", "green_onion": "l_onion", "meat": "raw_pork", "ham": "sliced_ham"}.items():
            self.connection.execute("UPDATE products SET class_name = ? WHERE class_name = ?", (new_name, old_name))
        self.connection.executemany("""INSERT INTO products (class_name, product_name, price) VALUES (?, ?, ?)
            ON CONFLICT(class_name) DO UPDATE SET product_name = excluded.product_name, price = excluded.price""", PRODUCTS)
        self.connection.executemany("INSERT OR IGNORE INTO recipes (recipe_name, description) VALUES (?, ?)", RECIPES)
        for recipe_name, class_names in RECIPE_INGREDIENTS.items():
            recipe_id = self.connection.execute("SELECT recipe_id FROM recipes WHERE recipe_name = ?", (recipe_name,)).fetchone()[0]
            for class_name in class_names:
                product_id = self.connection.execute("SELECT product_id FROM products WHERE class_name = ?", (class_name,)).fetchone()[0]
                self.connection.execute("INSERT OR IGNORE INTO recipe_ingredients (recipe_id, product_id) VALUES (?, ?)", (recipe_id, product_id))
        self.connection.commit()

    def get_product(self, class_name: str):
        class_name = self.normalize_class_name(class_name)
        return self.connection.execute("SELECT class_name, product_name, price FROM products WHERE class_name = ?", (class_name,)).fetchone()

    @staticmethod
    def normalize_class_name(class_name: str) -> str:
        normalized = class_name.strip().lower()
        return CLASS_NAME_ALIASES.get(normalized, normalized)

    def get_recipes(self, available_classes: set[str]) -> list[dict]:
        rows = self.connection.execute("""SELECT r.recipe_name, r.description, p.class_name, p.product_name FROM recipes r
            JOIN recipe_ingredients ri ON r.recipe_id = ri.recipe_id JOIN products p ON ri.product_id = p.product_id ORDER BY r.recipe_id, p.product_id""").fetchall()
        recipes: dict[str, dict] = {}
        for recipe_name, description, class_name, product_name in rows:
            recipe = recipes.setdefault(recipe_name, {"name": recipe_name, "description": description, "classes": [], "ingredients": []})
            recipe["classes"].append(class_name)
            recipe["ingredients"].append(product_name)
        result = []
        for recipe in recipes.values():
            needed, owned = set(recipe["classes"]), set(recipe["classes"]) & available_classes
            recipe.update(owned_count=len(owned), needed_count=len(needed), match_rate=len(owned) / len(needed) * 100, complete=owned == needed)
            # Recommend only recipes for which at least half of the required
            # ingredients are already in the cart.
            if recipe["match_rate"] >= 50:
                result.append(recipe)
        return sorted(result, key=lambda recipe: (recipe["match_rate"], recipe["owned_count"]), reverse=True)

    def close(self) -> None:
        self.connection.close()
