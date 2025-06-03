"""Test suite for SQLite storage backend."""
import os
import unittest
import tempfile
from datetime import datetime
from typing import Optional, Sequence, cast, Type, TypeVar

from hawkinsdb.storage.sqlite import SQLiteStorage
from hawkinsdb.types import CorticalColumn, ReferenceFrame, PropertyCandidate
from hawkinsdb.base import BaseCorticalColumn

# Type variable for CorticalColumn
T_CorticalColumn = TypeVar('T_CorticalColumn', bound=BaseCorticalColumn)

class TestSQLiteStorage(unittest.TestCase):
    """Test cases for SQLite storage backend."""
    
    def setUp(self):
        """Set up test environment with temporary database."""
        # Use temporary file for testing
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_hawkins.db")
        self.storage = SQLiteStorage(db_path=self.db_path)
        self.storage.initialize()
        
    def tearDown(self):
        """Clean up test environment."""
        self.storage.cleanup()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        os.rmdir(self.temp_dir)
        
    def test_initialize_and_cleanup(self):
        """Test database initialization and cleanup."""
        self.assertTrue(os.path.exists(self.db_path))
        self.storage.cleanup()
        
    def test_save_and_load_columns(self):
        """Test saving and loading columns with various data types."""
        # Create test data
        test_time = datetime.now().isoformat()
        test_columns: Sequence[T_CorticalColumn] = cast(
            Sequence[T_CorticalColumn],
            [
                CorticalColumn(
                    name="test_column",
                    frames=[
                        ReferenceFrame(
                            name="test_frame",
                            properties={
                                "color": [PropertyCandidate(value="red", confidence=0.9)],
                                "size": [PropertyCandidate(value=42, confidence=1.0)]
                            },
                            relationships={
                                "contains": [PropertyCandidate(value="item", confidence=0.8)]
                            },
                            location={"x": 0, "y": 0},
                            history=[(test_time, "created"), (test_time, "updated")]
                        )
                    ]
                )
            ]
        )
        
        # Save columns
        self.storage.save_columns(test_columns)
        
        # Load columns
        loaded_columns = self.storage.load_columns()
        
        # Verify data
        self.assertEqual(len(loaded_columns), 1)
        self.assertEqual(loaded_columns[0].name, "test_column")
        self.assertEqual(len(loaded_columns[0].frames), 1)
        
        loaded_frame = loaded_columns[0].frames[0]
        self.assertEqual(loaded_frame.name, "test_frame")
        self.assertEqual(loaded_frame.properties["color"][0].value, "red")
        self.assertEqual(loaded_frame.properties["size"][0].value, 42)
        self.assertEqual(loaded_frame.relationships["contains"][0].value, "item")
        self.assertEqual(loaded_frame.location, {"x": 0, "y": 0})
        self.assertEqual(loaded_frame.history, [(test_time, "created"), (test_time, "updated")])
        
    def test_error_handling(self):
        """Test error handling for invalid operations."""
        # Test saving invalid data (empty column name)
        with self.assertRaises(ValueError):
            invalid_columns: Sequence[T_CorticalColumn] = cast(
                Sequence[T_CorticalColumn], 
                [CorticalColumn(name="", frames=[])]
            )
            self.storage.save_columns(invalid_columns)
            
        # Test empty database path
        with self.assertRaises(ValueError) as cm:
            SQLiteStorage(db_path="")
        self.assertIn("Invalid database path", str(cm.exception))
            
        # Test non-existent directory creation
        with tempfile.TemporaryDirectory() as temp_dir:
            new_dir = os.path.join(temp_dir, "newdir")
            db_path = os.path.join(new_dir, "test.db")
            storage = SQLiteStorage(db_path=db_path)
            self.assertTrue(os.path.exists(new_dir))
            storage.cleanup()
            
        # Test invalid directory permissions
        if os.name != 'nt':  # Skip on Windows
            with tempfile.TemporaryDirectory() as temp_dir:
                # Create a read-only directory
                read_only_dir = os.path.join(temp_dir, "readonly")
                os.makedirs(read_only_dir)
                os.chmod(read_only_dir, 0o555)  # Read + execute only
                
                db_path = os.path.join(read_only_dir, "test.db")
                with self.assertRaises(ValueError) as cm:
                    SQLiteStorage(db_path=db_path)
                self.assertIn("write", str(cm.exception).lower())

    def test_update_entity(self):
        """Test updating an entity in SQLiteStorage."""
        import sqlite3
        import json
        import time

        # Initial data
        column_name = "TestColumn"
        frame_name = "TestFrame"
        initial_properties = {"feature": "initial_value", "color": "blue"}
        initial_relationships = {"connected_to": "another_frame"}
        initial_location = {"x": 10, "y": 20}
        created_at_dt = datetime.now()
        created_at_iso = created_at_dt.isoformat()
        # Ensure updated_at is slightly different if possible, or same for simplicity in setup
        updated_at_iso = created_at_dt.isoformat() 

        # 1. Setup: Add a column and a frame directly
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO columns (name, created_at, updated_at) VALUES (?, ?, ?)",
                               (column_name, created_at_iso, updated_at_iso))
                column_id = cursor.lastrowid
                cursor.execute("""
                    INSERT INTO frames (name, column_id, properties, relationships, location, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (frame_name, column_id, json.dumps(initial_properties), json.dumps(initial_relationships),
                      json.dumps(initial_location), created_at_iso, updated_at_iso))
                conn.commit()
        except sqlite3.Error as e:
            self.fail(f"DB setup failed: {e}")

        # Allow a small delay to ensure timestamps can differ
        time.sleep(0.01)

        # 2. Test successful update
        update_data = {
            "properties": {"feature": "updated_value", "size": 30},
            "relationships": {"connected_to": "new_frame", "sibling_of": "frame_b"},
            "location": {"x": 15, "y": 25, "z": 5}
        }
        self.assertTrue(self.storage.update_entity(column_name, frame_name, update_data), "Update_entity should succeed.")

        # Verify update in DB
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT f.properties, f.relationships, f.location, f.updated_at
                FROM frames f
                JOIN columns c ON f.column_id = c.id
                WHERE c.name = ? AND f.name = ?
            """, (column_name, frame_name))
            row = cursor.fetchone()
            self.assertIsNotNone(row, "Updated frame should exist.")
            self.assertEqual(json.loads(row["properties"]), update_data["properties"])
            self.assertEqual(json.loads(row["relationships"]), update_data["relationships"])
            self.assertEqual(json.loads(row["location"]), update_data["location"])
            self.assertGreater(row["updated_at"], updated_at_iso, "updated_at should be newer.")
            original_updated_at_for_next_test = row["updated_at"]

        # 3. Test update with empty data (should only update updated_at)
        time.sleep(0.01)
        empty_update_data = {}
        self.assertTrue(self.storage.update_entity(column_name, frame_name, empty_update_data), "Update with empty data should succeed.")
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT properties, updated_at FROM frames WHERE name = ? AND column_id = (SELECT id FROM columns WHERE name = ?)", 
                           (frame_name, column_name))
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            # Properties should remain unchanged from the previous update
            self.assertEqual(json.loads(row["properties"]), update_data["properties"]) 
            self.assertGreater(row["updated_at"], original_updated_at_for_next_test, "updated_at should be newer after empty update.")

        # 4. Test update of only one field (e.g., properties)
        time.sleep(0.01)
        partial_update_data = {"properties": {"feature": "final_value"}}
        self.assertTrue(self.storage.update_entity(column_name, frame_name, partial_update_data))
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT properties, relationships, location, updated_at FROM frames WHERE name = ? AND column_id = (SELECT id FROM columns WHERE name = ?)", 
                           (frame_name, column_name))
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(json.loads(row["properties"]), partial_update_data["properties"])
             # Relationships and location should remain from the first successful update_data
            self.assertEqual(json.loads(row["relationships"]), update_data["relationships"])
            self.assertEqual(json.loads(row["location"]), update_data["location"])
            self.assertGreater(row["updated_at"], original_updated_at_for_next_test)


        # 5. Test update for non-existent frame
        self.assertFalse(self.storage.update_entity(column_name, "NonExistentFrame", update_data), "Update for non-existent frame should fail.")

        # 6. Test update for frame in non-existent column
        self.assertFalse(self.storage.update_entity("NonExistentColumn", frame_name, update_data), "Update for non-existent column should fail.")

        # 7. Test update with only some fields in data
        time.sleep(0.01)
        another_partial_update = {"location": {"x": 100}}
        last_updated_at = row["updated_at"] # from previous fetch
        self.assertTrue(self.storage.update_entity(column_name, frame_name, another_partial_update))
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT properties, relationships, location, updated_at FROM frames WHERE name = ? AND column_id = (SELECT id FROM columns WHERE name = ?)", 
                           (frame_name, column_name))
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(json.loads(row["properties"]), partial_update_data["properties"]) # from previous partial
            self.assertEqual(json.loads(row["relationships"]), update_data["relationships"]) # from first update
            self.assertEqual(json.loads(row["location"]), another_partial_update["location"]) # newly updated
            self.assertGreater(row["updated_at"], last_updated_at)


if __name__ == '__main__':
    unittest.main()