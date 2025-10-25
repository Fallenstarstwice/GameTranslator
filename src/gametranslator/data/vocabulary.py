"""
Vocabulary database for GameTranslator.
Manages multiple vocabulary books and their entries.
"""

import os
import sqlite3
import shutil
from pathlib import Path
import datetime

from src.gametranslator.config.settings import settings


class VocabularyDB:
    """Manages the vocabulary database which contains multiple books."""

    def __init__(self, db_path=None):
        """
        Initialize the vocabulary database.
        If db_path is not provided, it defaults to a path within the package.
        Also handles one-time migration from the old user-level directory.
        """
        if db_path:
            self.db_path = Path(db_path)
        else:
            # New default path is in src/gametranslator/data/sqlfiles
            base_dir = Path(__file__).parent
            self.db_path = base_dir / "sqlfiles" / "vocabulary.db"

        # --- One-time migration of the DB file from old location ---
        old_db_path = Path.home() / ".gametranslator" / "vocabulary.db"
        if old_db_path.exists() and not self.db_path.exists():
            try:
                print(f"Migrating database from {old_db_path} to {self.db_path}...")
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(old_db_path, self.db_path)
                print("Migration successful.")
            except Exception as e:
                print(f"Error migrating database file: {e}")
        
        self.db_dir = self.db_path.parent
        self.db_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize database (this will also handle schema migration)
        self._init_db()

    def _get_connection(self):
        """Returns a database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self):
        """Initialize the database schema and performs necessary migrations."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. Create books table (always safe)
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''')
            
            # 2. Create vocabulary table if it doesn't exist (for old schema)
            # This version of the table is intentionally missing the 'book_id'
            # to match the state of an old database.
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS vocabulary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original TEXT NOT NULL,
                translation TEXT NOT NULL,
                source_lang TEXT,
                target_lang TEXT,
                context TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''')

            # 3. MIGRATION: Check for 'book_id' column and add it if missing
            cursor.execute("PRAGMA table_info(vocabulary)")
            columns = [row['name'] for row in cursor.fetchall()]
            
            if 'book_id' not in columns:
                print("Old database schema detected. Migrating 'vocabulary' table...")
                try:
                    cursor.execute("ALTER TABLE vocabulary ADD COLUMN book_id INTEGER")
                    
                    # Ensure a 'Default' book exists and get its ID
                    cursor.execute("SELECT id FROM books WHERE name = 'Default'")
                    default_book = cursor.fetchone()
                    if not default_book:
                        cursor.execute("INSERT INTO books (name, description) VALUES (?, ?)", ("Default", "Default vocabulary book"))
                        default_book_id = cursor.lastrowid
                    else:
                        default_book_id = default_book['id']

                    # Assign all existing entries to the default book
                    cursor.execute("UPDATE vocabulary SET book_id = ? WHERE book_id IS NULL", (default_book_id,))
                    print("Migration: Assigned existing entries to 'Default' book.")
                except sqlite3.OperationalError as e:
                    # This can happen if a previous migration was interrupted.
                    # If the column already exists but this code runs, we can ignore it.
                    if "duplicate column name" not in str(e):
                        raise e
            
            # 4. Ensure a default book exists for brand new DBs
            cursor.execute("SELECT id FROM books LIMIT 1")
            if cursor.fetchone() is None:
                cursor.execute("INSERT INTO books (name, description) VALUES (?, ?)", 
                               ("Default", "Default vocabulary book"))

            conn.commit()

    # --- Book Management ---

    def create_book(self, name, description=""):
        """
        Creates a new vocabulary book.
        
        Args:
            name (str): The name of the book. Must be unique.
            description (str, optional): A short description for the book.
            
        Returns:
            int: The ID of the newly created book.
        
        Raises:
            sqlite3.IntegrityError: If a book with the same name already exists.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO books (name, description) VALUES (?, ?)", (name, description))
            conn.commit()
            return cursor.lastrowid

    def get_all_books(self):
        """
        Retrieves all vocabulary books.
        
        Returns:
            list: A list of dictionaries, where each dictionary represents a book.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM books ORDER BY name")
            return [dict(row) for row in cursor.fetchall()]

    def rename_book(self, book_id, new_name):
        """
        Renames a vocabulary book.
        
        Args:
            book_id (int): The ID of the book to rename.
            new_name (str): The new name for the book.
        """
        with self._get_connection() as conn:
            conn.execute("UPDATE books SET name = ? WHERE id = ?", (new_name, book_id))
            conn.commit()

    def delete_book(self, book_id):
        """
        Deletes a vocabulary book and all its entries.
        
        Args:
            book_id (int): The ID of the book to delete.
        """
        with self._get_connection() as conn:
            conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
            conn.commit()

    # --- Entry Management ---

    def add_entry(self, book_id, original, translation, source_lang=None, target_lang=None, context=None):
        """
        Add a new vocabulary entry to a specific book.
        
        Args:
            book_id (int): The ID of the book to add the entry to.
            original (str): Original text.
            translation (str): Translated text.
            source_lang (str, optional): Source language code.
            target_lang (str, optional): Target language code.
            context (str, optional): Context where the text was found.
            
        Returns:
            int: ID of the new entry.
        """
        if not source_lang:
            source_lang = settings.get("translation", "source_language", "auto")
        
        if not target_lang:
            target_lang = settings.get("translation", "target_language", "zh-CN")
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO vocabulary (book_id, original, translation, source_lang, target_lang, context)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (book_id, original, translation, source_lang, target_lang, context))
            conn.commit()
            return cursor.lastrowid

    def get_entries_by_book(self, book_id, limit=100, offset=0):
        """
        Get vocabulary entries for a specific book.
        
        Args:
            book_id (int): The ID of the book.
            limit (int, optional): Maximum number of entries to return.
            offset (int, optional): Offset for pagination.
            
        Returns:
            list: List of vocabulary entries for the given book.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            SELECT * FROM vocabulary
            WHERE book_id = ?
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            ''', (book_id, limit, offset))
            return [dict(row) for row in cursor.fetchall()]

    def search_entries_in_book(self, book_id, query, limit=100):
        """
        Search vocabulary entries within a specific book.
        
        Args:
            book_id (int): The ID of the book to search in.
            query (str): Search query.
            limit (int, optional): Maximum number of entries to return.
            
        Returns:
            list: List of matching vocabulary entries.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            SELECT * FROM vocabulary
            WHERE book_id = ? AND (original LIKE ? OR translation LIKE ?)
            ORDER BY created_at DESC
            LIMIT ?
            ''', (book_id, f'%{query}%', f'%{query}%', limit))
            return [dict(row) for row in cursor.fetchall()]

    def update_entry(self, entry_id, original=None, translation=None):
        """
        Updates an existing vocabulary entry.
        Only updates fields that are not None.
        
        Args:
            entry_id (int): The ID of the entry to update.
            original (str, optional): The new original text.
            translation (str, optional): The new translation.
        """
        fields = []
        params = []
        if original is not None:
            fields.append("original = ?")
            params.append(original)
        if translation is not None:
            fields.append("translation = ?")
            params.append(translation)
        
        if not fields:
            return # Nothing to update
            
        params.append(entry_id)
        
        with self._get_connection() as conn:
            sql = f"UPDATE vocabulary SET {', '.join(fields)} WHERE id = ?"
            conn.execute(sql, tuple(params))
            conn.commit()

    def delete_entry(self, entry_id):
        """
        Deletes a vocabulary entry.
        
        Args:
            entry_id (int): The ID of the entry to delete.
        """
        with self._get_connection() as conn:
            conn.execute("DELETE FROM vocabulary WHERE id = ?", (entry_id,))
            conn.commit()