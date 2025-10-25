"""
Vocabulary view UI for GameTranslator.
Manages vocabulary entries and books (ChromaDB collections).
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLineEdit, QLabel, QHeaderView, QMessageBox, QComboBox,
    QInputDialog, QDialog, QDialogButtonBox, QFormLayout
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
import logging
from typing import List, Dict, Any, Optional

from src.gametranslator.core.vocabulary_db import VocabularyDB

log = logging.getLogger(__name__)


# --- Custom Dialog for Manual Entry ---
class AddEntryDialog(QDialog):
    """A dialog for manually adding a new vocabulary entry."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("手动添加词条")
        
        layout = QVBoxLayout(self)
        
        form_layout = QFormLayout()
        self.original_input = QLineEdit()
        self.translation_input = QLineEdit()
        form_layout.addRow("原文:", self.original_input)
        form_layout.addRow("翻译:", self.translation_input)
        
        layout.addLayout(form_layout)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        
        layout.addWidget(buttons)

    def get_texts(self):
        """Returns the entered texts if the dialog is accepted."""
        return self.original_input.text().strip(), self.translation_input.text().strip()

    @staticmethod
    def get_entry(parent=None):
        """Static method to create, show the dialog, and return the texts."""
        dialog = AddEntryDialog(parent)
        result = dialog.exec()
        if result == QDialog.DialogCode.Accepted:
            return dialog.get_texts()
        return None, None


class VocabularyView(QWidget):
    """Vocabulary view widget for managing ChromaDB collections (books)."""

    collections_changed = Signal()
    manual_add_requested = Signal(str, str)
    embedding_config_requested = Signal()

    def __init__(self, vocabulary_db: VocabularyDB):
        super().__init__()
        
        self.db = vocabulary_db
        self.dirty_rows = set()
        
        self.main_layout = QVBoxLayout(self)
        self.setLayout(self.main_layout)
        
        self.create_collection_controls()
        self.create_search_bar()
        self.create_table()
        self.create_entry_buttons()
        
        self.table.itemChanged.connect(self.on_item_changed)
        self.load_collections()

    def create_collection_controls(self):
        """Create controls for managing vocabulary books (collections)."""
        coll_layout = QHBoxLayout()
        coll_layout.addWidget(QLabel("词汇本:"))
        
        self.collection_combo = QComboBox()
        self.collection_combo.currentTextChanged.connect(self.on_collection_changed)
        coll_layout.addWidget(self.collection_combo)
        
        self.new_coll_button = QPushButton("新建")
        self.new_coll_button.clicked.connect(self.new_collection)
        coll_layout.addWidget(self.new_coll_button)
        
        self.rename_coll_button = QPushButton("重命名")
        self.rename_coll_button.clicked.connect(self.rename_collection)
        coll_layout.addWidget(self.rename_coll_button)
        
        self.delete_coll_button = QPushButton("删除")
        self.delete_coll_button.clicked.connect(self.delete_collection)
        coll_layout.addWidget(self.delete_coll_button)
        
        self.main_layout.addLayout(coll_layout)

    def create_search_bar(self):
        """Create search bar for entries within a collection."""
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("搜索 (相似度):"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("在当前词汇本中搜索...")
        self.search_input.returnPressed.connect(self.load_entries)
        search_layout.addWidget(self.search_input)
        
        self.search_button = QPushButton("搜索")
        self.search_button.clicked.connect(self.load_entries)
        search_layout.addWidget(self.search_button)

        self.main_layout.addLayout(search_layout)

    def create_table(self):
        """Create vocabulary table."""
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["ID", "原文", "翻译", "语言", "相似度"])
        
        self.table.setColumnHidden(0, True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        
        self.main_layout.addWidget(self.table)

    def create_entry_buttons(self):
        """Create action buttons for entries."""
        button_layout = QHBoxLayout()
        
        self.manual_add_button = QPushButton("手动添加")
        self.manual_add_button.clicked.connect(self.manual_add_entry)
        button_layout.addWidget(self.manual_add_button)

        self.delete_entry_button = QPushButton("删除选中词条")
        self.delete_entry_button.clicked.connect(self.delete_selected_entries)
        button_layout.addWidget(self.delete_entry_button)
        
        self.refresh_button = QPushButton("刷新 (显示全部)")
        self.refresh_button.clicked.connect(self.refresh_all_entries)
        button_layout.addWidget(self.refresh_button)
        
        button_layout.addStretch()

        self.save_button = QPushButton("保存修改")
        self.save_button.clicked.connect(self.save_changes)
        button_layout.addWidget(self.save_button)

        self.main_layout.addLayout(button_layout)

    def manual_add_entry(self):
        """Opens a dialog to manually add a new entry."""
        original, translation = AddEntryDialog.get_entry(self)
        if original and translation:
            self.manual_add_requested.emit(original, translation)

    def on_item_changed(self, item: QTableWidgetItem):
        """Mark a row as dirty when its content changes."""
        row = item.row()
        self.dirty_rows.add(row)
        # Visually mark the row as modified
        for col in range(self.table.columnCount()):
            cell_item = self.table.item(row, col)
            if cell_item:
                cell_item.setBackground(QColor("#454520")) # A yellowish tint

    def save_changes(self):
        """Saves all modified entries to the database."""
        collection_name = self.current_collection_name
        if not collection_name:
            QMessageBox.warning(self, "无词汇本", "没有可保存的词汇本。")
            return

        if not self.dirty_rows:
            QMessageBox.information(self, "无修改", "没有检测到任何修改。")
            return

        log.info(f"Saving {len(self.dirty_rows)} modified entries to '{collection_name}'...")
        
        saved_count = 0
        error_count = 0

        # Configure embedding provider before saving
        self.embedding_config_requested.emit() # Signal to main window to get credentials

        for row in sorted(list(self.dirty_rows)):
            try:
                id_item = self.table.item(row, 0)
                original_item = self.table.item(row, 1)
                translation_item = self.table.item(row, 2)
                
                if not all([id_item, original_item, translation_item]):
                    log.warning(f"Skipping row {row} due to missing items.")
                    error_count += 1
                    continue

                entry_id = id_item.text()
                original_text = original_item.text()
                translation_text = translation_item.text()

                # Retrieve existing metadata to preserve it
                metadata_item = self.table.item(row, 3) # Assuming lang is in column 3
                metadata = {}
                if metadata_item:
                    # This is a simplification. A more robust solution would store
                    # the full metadata dict somewhere, e.g., in a custom item role.
                    # For now, we just reconstruct what we can.
                    langs = metadata_item.text().split(" → ")
                    if len(langs) == 2:
                        metadata['source_lang'] = langs[0]
                        metadata['target_lang'] = langs[1]

                self.db.update_entry(
                    collection_name=collection_name,
                    entry_id=entry_id,
                    new_original_text=original_text,
                    new_translation=translation_text,
                    metadata=metadata
                )
                saved_count += 1
                # Reset row color on successful save
                for col in range(self.table.columnCount()):
                    cell_item = self.table.item(row, col)
                    if cell_item:
                        cell_item.setBackground(QColor(Qt.GlobalColor.transparent))

            except Exception as e:
                error_count += 1
                log.error(f"Failed to save entry at row {row}: {e}", exc_info=True)
                # Keep row colored to indicate error
                for col in range(self.table.columnCount()):
                    cell_item = self.table.item(row, col)
                    if cell_item:
                        cell_item.setBackground(QColor("#581111")) # Reddish tint

        self.dirty_rows.clear()

        if error_count > 0:
            QMessageBox.warning(self, "保存完成", f"成功保存 {saved_count} 个词条，{error_count} 个失败。请检查日志获取详情。")
        else:
            QMessageBox.information(self, "保存成功", f"所有 {saved_count} 个修改已成功保存。")
        
        self.load_entries() # Refresh to show updated state

    @property
    def current_collection_name(self) -> Optional[str]:
        """Returns the name of the currently selected collection."""
        return self.collection_combo.currentText() or None

    def load_collections(self):
        """Load vocabulary books from DB and populate the combobox."""
        self.collection_combo.blockSignals(True)
        self.collection_combo.clear()
        try:
            collections = self.db.list_collections()
            if not collections:
                log.info("No collections found. Creating a 'default' collection.")
                self.db.create_collection("default")
                collections = self.db.list_collections()

            for coll in collections:
                self.collection_combo.addItem(coll['name'], coll['id'])
            
            self.collections_changed.emit()

        except Exception as e:
            log.error(f"Failed to load collections: {e}", exc_info=True)
            QMessageBox.critical(self, "错误", f"加载词汇本列表失败: {e}")
        finally:
            self.collection_combo.blockSignals(False)
        
        self.on_collection_changed(self.collection_combo.currentText())

    def on_collection_changed(self, collection_name: str):
        """Handle collection selection change."""
        if self.dirty_rows:
            reply = QMessageBox.question(
                self, "未保存的修改",
                "您有未保存的修改。如果切换词汇本，这些修改将会丢失。要继续吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                # Find the index of the previous collection and reset the combo box
                # This is a bit tricky if the text is not unique, but usually it is.
                # A more robust way would be to store the previous index.
                return # Abort the change
        
        self.dirty_rows.clear()
        log.debug(f"Switched to collection: {collection_name}")
        self.search_input.clear()
        self.load_entries()

    def new_collection(self):
        """Create a new collection."""
        name, ok = QInputDialog.getText(self, "新建词汇本", "请输入新词汇本的名称:")
        if ok and name:
            try:
                self.db.create_collection(name)
                self.load_collections()
                self.collection_combo.setCurrentText(name)
            except Exception as e:
                log.error(f"Failed to create collection '{name}': {e}", exc_info=True)
                QMessageBox.critical(self, "错误", f"创建词汇本 '{name}' 失败: {e}")

    def rename_collection(self):
        """Rename the current collection."""
        current_name = self.current_collection_name
        if not current_name:
            QMessageBox.warning(self, "无选择", "请先选择一个要重命名的词汇本。")
            return

        new_name, ok = QInputDialog.getText(self, "重命名词汇本", f"为 '{current_name}' 输入新名称:", text=current_name)
        if ok and new_name and new_name != current_name:
            try:
                self.db.rename_collection(current_name, new_name)
                self.load_collections()
                self.collection_combo.setCurrentText(new_name)
            except Exception as e:
                log.error(f"Failed to rename collection '{current_name}': {e}", exc_info=True)
                QMessageBox.critical(self, "错误", f"重命名失败: {e}")

    def delete_collection(self):
        """Delete the current collection."""
        current_name = self.current_collection_name
        if not current_name:
            QMessageBox.warning(self, "无选择", "请先选择一个要删除的词汇本。")
            return

        reply = QMessageBox.question(
            self, "确认删除", f"确定要删除词汇本 '{current_name}' 及其所有内容吗？此操作无法撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                self.db.delete_collection(current_name)
                self.load_collections()
            except Exception as e:
                log.error(f"Failed to delete collection '{current_name}': {e}", exc_info=True)
                QMessageBox.critical(self, "错误", f"删除失败: {e}")

    def refresh_all_entries(self):
        """Clears search and loads all entries for the current collection."""
        if self.dirty_rows:
            reply = QMessageBox.question(
                self, "未保存的修改",
                "您有未保存的修改。如果刷新，这些修改将会丢失。要继续吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
        
        self.dirty_rows.clear()
        self.search_input.clear()
        self.load_entries()

    def load_entries(self):
        """Load entries for the current collection, with optional search."""
        collection_name = self.current_collection_name
        if not self.db or not collection_name:
            self.table.setRowCount(0)
            return
            
        query = self.search_input.text().strip()
        
        try:
            if query:
                self.embedding_config_requested.emit() # Ensure provider is configured
                entries = self.db.query(collection_name, query, n_results=100)
                self.table.setColumnHidden(4, False)
            else:
                entries = self.db.get_all_entries(collection_name, limit=1000)
                self.table.setColumnHidden(4, True)
            
            self.display_entries(entries if entries else [])

        except RuntimeError as e:
            QMessageBox.warning(self, "配置错误", f"无法加载词条: {e}\n请前往“设置”页面配置并保存词汇本设置。")
        except Exception as e:
            log.error(f"加载词条时出错: {e}", exc_info=True)
            QMessageBox.critical(self, "错误", f"加载词条时出错: {e}")

    def display_entries(self, entries: List[Dict[str, Any]]):
        """Display entries in the table."""
        self.table.blockSignals(True) # Block signals during population
        self.table.setRowCount(0)
        self.dirty_rows.clear()

        for entry in entries:
            row = self.table.rowCount()
            self.table.insertRow(row)
            
            # ID (column 0) - not editable
            id_item = QTableWidgetItem(str(entry.get("id", "")))
            id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, id_item)
            
            # Original Text (column 1) - editable
            original_item = QTableWidgetItem(entry.get("original_text", ""))
            self.table.setItem(row, 1, original_item)
            
            # Translation (column 2) - editable
            metadata = entry.get("metadata", {})
            translation_item = QTableWidgetItem(metadata.get("translation", ""))
            self.table.setItem(row, 2, translation_item)
            
            # Language (column 3) - not editable
            lang_text = f"{metadata.get('source_lang', 'N/A')} → {metadata.get('target_lang', 'N/A')}"
            lang_item = QTableWidgetItem(lang_text)
            lang_item.setFlags(lang_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 3, lang_item)

            # Distance (column 4) - not editable
            distance = entry.get('distance')
            if distance is not None:
                dist_item = QTableWidgetItem(f"{distance:.4f}")
                dist_item.setFlags(dist_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, 4, dist_item)

        self.table.blockSignals(False) # Re-enable signals

    def delete_selected_entries(self):
        """Delete selected entries from the current collection."""
        collection_name = self.current_collection_name
        if not collection_name:
            return

        selection_model = self.table.selectionModel()
        if not selection_model or not selection_model.hasSelection():
            QMessageBox.information(self, "无选中", "请先选择要删除的词条。")
            return

        selected_rows = [index.row() for index in self.table.selectionModel().selectedRows()]
        
        reply = QMessageBox.question(
            self, "确认删除", f"确定要从 '{collection_name}' 中删除选中的 {len(selected_rows)} 个词条吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            ids_to_delete = []
            for row in selected_rows:
                item = self.table.item(row, 0)
                if item:
                    ids_to_delete.append(item.text())
            
            if ids_to_delete:
                try:
                    self.db.delete_entry(collection_name, ids_to_delete)
                    self.load_entries()
                except Exception as e:
                    log.error(f"删除词条时出错: {e}", exc_info=True)
                    QMessageBox.critical(self, "错误", f"删除词条时出错: {e}")