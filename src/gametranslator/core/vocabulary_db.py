# -*- coding: utf-8 -*-
"""
This module implements the vocabulary database using ChromaDB and online embedding models.
"""
import chromadb
import os
import json
from openai import OpenAI
from typing import List, Dict, Any, Optional

class VocabularyDB:
    """
    Manages the vocabulary database using ChromaDB for vector storage and querying.
    Each vocabulary book is managed as a separate ChromaDB collection.
    """

    def __init__(self, db_path: str = "db/vocabulary"):
        """
        Initializes the VocabularyDB.

        Args:
            db_path (str): Path to the ChromaDB persistent storage directory.
        """
        self.db_path = db_path
        self._client: Optional[chromadb.PersistentClient] = None
        self._embedding_client: Optional[OpenAI] = None
        self._embedding_model: Optional[str] = None

    def _get_client(self) -> chromadb.PersistentClient:
        """Initializes and returns the ChromaDB client."""
        if not self._client:
            self._client = chromadb.PersistentClient(path=self.db_path)
        return self._client

    def _get_collection(self, collection_name: str) -> chromadb.Collection:
        """
        Retrieves a collection by name.

        Args:
            collection_name (str): The name of the collection (vocabulary book).

        Returns:
            chromadb.Collection: The collection object.
        """
        client = self._get_client()
        return client.get_collection(name=collection_name)

    def configure_embedding_provider(
        self,
        api_key: str,
        base_url: str,
        model: str
    ):
        """
        Configures the client for the selected embedding provider with explicit credentials.

        Args:
            api_key (str): The API key for the embedding service.
            base_url (str): The base URL of the embedding service API.
            model (str): The specific embedding model to use.

        Raises:
            ValueError: If any of the required parameters are missing.
        """
        if not all([api_key, base_url, model]):
            raise ValueError("API key, base URL, and model must be provided for embedding configuration.")

        self._embedding_client = OpenAI(
            api_key=api_key,
            base_url=base_url
        )
        self._embedding_model = model

    def _get_embedding(self, text: str) -> Optional[List[float]]:
        """
        Generates an embedding for the given text using the configured provider.

        Args:
            text (str): The text to embed.

        Returns:
            Optional[List[float]]: The embedding vector, or None if an error occurs.
        """
        if not self._embedding_client or not self._embedding_model:
            raise RuntimeError("Embedding provider is not configured. Call configure_embedding_provider() first.")
        
        try:
            response = self._embedding_client.embeddings.create(
                model=self._embedding_model,
                input=text,
                encoding_format='float'
            )
            return response.data[0].embedding
        except Exception as e:
            print(f"Error generating embedding: {e}")
            return None

    def list_collections(self) -> List[Dict[str, Any]]:
        """Lists all available vocabulary books (collections)."""
        client = self._get_client()
        collections = client.list_collections()
        return [{"id": col.id.hex, "name": col.name} for col in collections]

    def create_collection(self, collection_name: str):
        """Creates a new vocabulary book (collection)."""
        client = self._get_client()
        client.get_or_create_collection(name=collection_name)

    def delete_collection(self, collection_name: str):
        """Deletes a vocabulary book (collection)."""
        client = self._get_client()
        client.delete_collection(name=collection_name)

    def rename_collection(self, old_name: str, new_name: str):
        """Renames a collection by moving all items to a new one."""
        client = self._get_client()
        old_collection = client.get_collection(name=old_name)
        
        data = old_collection.get(include=["metadatas", "documents", "embeddings"])
        
        new_collection = client.get_or_create_collection(name=new_name)
        if data and data['ids']:
            new_collection.add(
                ids=data['ids'],
                embeddings=data['embeddings'],
                metadatas=data['metadatas'],
                documents=data['documents']
            )
        
        client.delete_collection(name=old_name)

    def add_entry(self, collection_name: str, original_text: str, translation: str, metadata: Optional[Dict[str, Any]] = None):
        """
        Adds a new vocabulary entry to a specific collection.

        Args:
            collection_name (str): The name of the vocabulary book.
            original_text (str): The original word or phrase.
            translation (str): The translated text.
            metadata (Optional[Dict[str, Any]]): Additional metadata to store.
        """
        collection = self._get_collection(collection_name)
        
        embedding = self._get_embedding(original_text)
        if not embedding:
            return

        doc_metadata = metadata or {}
        doc_metadata['translation'] = translation
        
        doc_id = f"{original_text.lower().replace(' ', '_')}"

        collection.upsert(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[original_text],
            metadatas=[doc_metadata]
        )

    def update_entry(self, collection_name: str, entry_id: str, new_original_text: str, new_translation: str, metadata: Optional[Dict[str, Any]] = None):
        """
        Updates an existing vocabulary entry.

        Args:
            collection_name (str): The name of the vocabulary book.
            entry_id (str): The ID of the entry to update.
            new_original_text (str): The new original text.
            new_translation (str): The new translation.
            metadata (Optional[Dict[str, Any]]): Existing metadata to be preserved or updated.
        """
        collection = self._get_collection(collection_name)

        embedding = self._get_embedding(new_original_text)
        if not embedding:
            # Decide on error handling: raise exception or log and return
            print(f"Failed to generate embedding for '{new_original_text}'. Update aborted.")
            return

        doc_metadata = metadata or {}
        doc_metadata['translation'] = new_translation

        # Upsert will update the entry if the ID already exists.
        collection.upsert(
            ids=[entry_id],
            embeddings=[embedding],
            documents=[new_original_text],
            metadatas=[doc_metadata]
        )

    def query(self, collection_name: str, query_text: str, n_results: int = 5) -> Optional[List[Dict[str, Any]]]:
        """
        Queries a specific collection for similar entries.

        Args:
            collection_name (str): The name of the vocabulary book to query.
            query_text (str): The text to search for.
            n_results (int): The number of results to return.

        Returns:
            A list of results, or None if an error occurs.
        """
        collection = self._get_collection(collection_name)

        query_embedding = self._get_embedding(query_text)
        if not query_embedding:
            return None

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["metadatas", "documents", "distances"]
        )
        
        formatted_results = []
        if results and results['ids'] and results['ids'][0]:
            for i, doc_id in enumerate(results['ids'][0]):
                formatted_results.append({
                    'id': doc_id,
                    'original_text': results['documents'][0][i],
                    'metadata': results['metadatas'][0][i],
                    'distance': results['distances'][0][i]
                })
        return formatted_results

    def get_all_entries(self, collection_name: str, limit: int = 1000, offset: int = 0) -> Optional[List[Dict[str, Any]]]:
        """
        Retrieves all entries from a specific collection with pagination.

        Args:
            collection_name (str): The name of the vocabulary book.
            limit (int): The number of entries to return.
            offset (int): The starting offset for retrieval.

        Returns:
            A list of entries.
        """
        collection = self._get_collection(collection_name)
        results = collection.get(
            limit=limit,
            offset=offset,
            include=["metadatas", "documents"]
        )
        
        formatted_results = []
        if results and results['ids']:
            for i, doc_id in enumerate(results['ids']):
                metadata = results['metadatas'][i] if results['metadatas'] and results['metadatas'][i] else {}
                document = results['documents'][i] if results['documents'] else ''
                
                formatted_results.append({
                    'id': doc_id,
                    'original_text': document,
                    'metadata': metadata,
                    'distance': 0.0 # Not applicable for get
                })
        return formatted_results

    def delete_entry(self, collection_name: str, entry_ids: List[str]):
        """
        Deletes vocabulary entries from a specific collection by their IDs.

        Args:
            collection_name (str): The name of the vocabulary book.
            entry_ids (List[str]): The list of entry IDs to delete.
        """
        collection = self._get_collection(collection_name)
        collection.delete(ids=entry_ids)

if __name__ == '__main__':
    # Example Usage
    print("Initializing VocabularyDB...")
    # Use a temporary path for testing
    vocab_db = VocabularyDB(db_path="db/test_vocabulary")
    
    # IMPORTANT: Set your API key in environment variables before running
    try:
        # This example now requires OPENAI_API_KEY to be set in the environment
        # as we are not using the config file for keys anymore.
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            print("Skipping example: OPENAI_API_KEY environment variable not set.")
            exit()
        vocab_db.configure_embedding_provider(
            api_key=api_key,
            base_url="https://api.openai.com/v1",
            model="text-embedding-3-small"
        )
    except (ValueError, RuntimeError) as e:
        print(f"Configuration Error: {e}")
        exit()

    # Define collection names
    dnd_collection = "dnd_terms"
    tech_collection = "tech_terms"

    # 1. Clean up previous runs and create collections
    print("\n--- Setting up collections ---")
    for coll in vocab_db.list_collections():
        print(f"Deleting existing collection: {coll['name']}")
        vocab_db.delete_collection(coll['name'])
    
    print(f"Creating collection: '{dnd_collection}'")
    vocab_db.create_collection(dnd_collection)
    print(f"Creating collection: '{tech_collection}'")
    vocab_db.create_collection(tech_collection)
    
    print("\nCurrent collections:")
    for coll in vocab_db.list_collections():
        print(f"- {coll['name']}")

    # 2. Add entries to specific collections
    print("\n--- Adding entries ---")
    print(f"Adding to '{dnd_collection}'...")
    vocab_db.add_entry(dnd_collection, "Mind Flayer", "夺心魔")
    vocab_db.add_entry(dnd_collection, "Beholder", "眼魔")
    
    print(f"Adding to '{tech_collection}'...")
    vocab_db.add_entry(tech_collection, "API", "应用程序编程接口")
    vocab_db.add_entry(tech_collection, "Container", "容器")
    print("Entries added.")

    # 3. Query a specific collection
    print(f"\n--- Querying '{dnd_collection}' for 'evil monster with tentacles' ---")
    query_results = vocab_db.query(dnd_collection, "evil monster with tentacles", n_results=1)
    if query_results:
        for result in query_results:
            print(f"  - Found: '{result['original_text']}' -> '{result['metadata'].get('translation')}', Distance: {result['distance']:.4f}")

    # 4. Get all entries from a collection
    print(f"\n--- All entries in '{tech_collection}' ---")
    all_tech_entries = vocab_db.get_all_entries(tech_collection)
    if all_tech_entries:
        for entry in all_tech_entries:
            print(f"- {entry['original_text']}: {entry['metadata'].get('translation')}")

    # 5. Rename a collection
    print("\n--- Renaming collection ---")
    renamed_tech_collection = "technical_jargon"
    print(f"Renaming '{tech_collection}' to '{renamed_tech_collection}'...")
    vocab_db.rename_collection(tech_collection, renamed_tech_collection)
    print("\nCurrent collections:")
    for coll in vocab_db.list_collections():
        print(f"- {coll['name']}")

    # 6. Delete an entry
    print("\n--- Deleting an entry ---")
    print(f"Deleting 'Beholder' from '{dnd_collection}'...")
    vocab_db.delete_entry(dnd_collection, entry_ids=["beholder"])
    all_dnd_entries = vocab_db.get_all_entries(dnd_collection)
    print(f"Current entries in '{dnd_collection}':")
    if all_dnd_entries:
        for entry in all_dnd_entries:
            print(f"- {entry['original_text']}")