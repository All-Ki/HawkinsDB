import logging
import unittest
import tempfile
import os
import time
from datetime import datetime
from hawkinsdb import HawkinsDB

logging.basicConfig(level=logging.INFO)

class TestHawkinsDBCore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_hawkins_core.db")
        # Ensure storage_type is explicitly sqlite for these tests
        self.db = HawkinsDB(db_path=self.db_path, storage_type='sqlite')
        # Ensure default columns are there if needed by add_entity or other ops
        self.db._initialize_memory_types()


    def tearDown(self):
        self.db.cleanup()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        os.rmdir(self.temp_dir)

    def test_add_and_query_entity(self):
        """Test basic add and query functionality."""
        initial_entity_data = {
            "column": "Semantic", # Using one of the default columns
            "name": "TestEntity1",
            "properties": {"color": "red", "size": "large"},
            "relationships": {"is_a": "test_concept"},
            "location": {"room": "A101"}
        }
        add_result = self.db.add_entity(initial_entity_data)
        self.assertTrue(add_result["success"])
        self.assertEqual(add_result["entity_name"], "testentity1")

        query_result = self.db.query_frames("TestEntity1")
        self.assertIn("Semantic", query_result)
        queried_frame = query_result["Semantic"]
        
        self.assertEqual(queried_frame.name, "TestEntity1")
        # Properties in ReferenceFrame are lists of PropertyCandidate
        self.assertEqual(queried_frame.properties["color"][0].value, "red")
        self.assertEqual(queried_frame.properties["size"][0].value, "large")
        self.assertEqual(queried_frame.relationships["is_a"][0].value, "test_concept")
        self.assertEqual(queried_frame.location["room"], "A101")


    def test_update_entity_core(self):
        """Test the update_entity functionality in HawkinsDB."""
        column_name = "Episodic" # Using one of the default columns
        entity_name = "TestEvent"
        
        initial_entity_data = {
            "column": column_name,
            "name": entity_name,
            "properties": {"type": "meeting", "duration": 60, "timestamp": datetime.now().isoformat()},
            "relationships": {"attendee": "John Doe"},
            "location": {"room": "Conference Room 1"}
        }
        
        add_result = self.db.add_entity(initial_entity_data)
        self.assertTrue(add_result.get("success"), f"Add entity failed: {add_result.get('message')}")

        # Allow a small delay to ensure timestamps can differ if updated
        time.sleep(0.01)
        
        update_data = {
            "properties": {"type": "workshop", "duration": 120, "status": "completed"},
            "relationships": {"attendee": ["John Doe", "Jane Smith"]}, # Update relationship
            "location": {"room": "Workshop Room 3"}
        }
        
        # --- Test successful update ---
        update_result = self.db.update_entity(column_name, entity_name, update_data)
        self.assertTrue(update_result["success"], f"Update failed: {update_result.get('message')}")
        self.assertEqual(update_result["message"], "Entity updated successfully.")

        # Verify with query_frames
        queried_frames = self.db.query_frames(entity_name)
        self.assertIn(column_name, queried_frames)
        updated_frame_queried = queried_frames[column_name]

        self.assertEqual(updated_frame_queried.properties["type"][0].value, "workshop")
        self.assertEqual(updated_frame_queried.properties["duration"][0].value, 120)
        self.assertEqual(updated_frame_queried.properties["status"][0].value, "completed")
        # Check if original timestamp is still there if not updated (depends on add_entity logic for properties)
        # For this test, we are overwriting properties, so original timestamp won't be there unless re-added.
        # Let's assume update_data completely replaces properties, so we check for 'status'
        self.assertNotIn("timestamp", updated_frame_queried.properties) # Assuming full replace of properties

        self.assertEqual(updated_frame_queried.relationships["attendee"][0].value, ["John Doe", "Jane Smith"])
        self.assertEqual(updated_frame_queried.location["room"], "Workshop Room 3")
        
        # Verify updated_at timestamp (it should be different from created_at)
        # Need to access raw frame data for created_at vs updated_at
        raw_frame_in_cols = None
        for frame in self.db.columns[column_name]["frames"]:
            if frame["name"] == entity_name:
                raw_frame_in_cols = frame
                break
        self.assertIsNotNone(raw_frame_in_cols)
        self.assertIn("created_at", raw_frame_in_cols)
        self.assertIn("updated_at", raw_frame_in_cols)
        if raw_frame_in_cols["created_at"] and raw_frame_in_cols["updated_at"]: # Ensure they exist
             self.assertGreater(raw_frame_in_cols["updated_at"], raw_frame_in_cols["created_at"], 
                               "updated_at should be greater than created_at after update.")
        original_updated_at = raw_frame_in_cols["updated_at"]


        # Verify in-memory consistency: db.columns
        self.assertEqual(raw_frame_in_cols["properties"], update_data["properties"])
        self.assertEqual(raw_frame_in_cols["relationships"], update_data["relationships"])
        self.assertEqual(raw_frame_in_cols["location"], update_data["location"])

        # Verify in-memory consistency: db.name_index
        entity_name_lower = entity_name.lower()
        indexed_frame_data = None
        for col_name_idx, frame_idx_data in self.db.name_index.get(entity_name_lower, []):
            if col_name_idx == column_name and frame_idx_data["name"] == entity_name:
                indexed_frame_data = frame_idx_data
                break
        self.assertIsNotNone(indexed_frame_data, "Frame not found in name_index or mismatch.")
        self.assertEqual(indexed_frame_data["properties"], update_data["properties"])
        self.assertEqual(indexed_frame_data["updated_at"], original_updated_at) # Timestamps should match

        # --- Test update with only one field ---
        time.sleep(0.01)
        partial_update = {"location": {"room": "Main Hall", "floor": 1}}
        update_result_partial = self.db.update_entity(column_name, entity_name, partial_update)
        self.assertTrue(update_result_partial["success"])
        
        queried_frames_partial = self.db.query_frames(entity_name)
        updated_frame_partial_queried = queried_frames_partial[column_name]
        self.assertEqual(updated_frame_partial_queried.location["room"], "Main Hall")
        self.assertEqual(updated_frame_partial_queried.location["floor"], 1)
        # Properties should remain from 'update_data'
        self.assertEqual(updated_frame_partial_queried.properties["type"][0].value, "workshop")

        raw_frame_in_cols_partial = None
        for frame in self.db.columns[column_name]["frames"]:
            if frame["name"] == entity_name:
                raw_frame_in_cols_partial = frame
                break
        self.assertIsNotNone(raw_frame_in_cols_partial)
        self.assertGreater(raw_frame_in_cols_partial["updated_at"], original_updated_at)


        # --- Test edge cases ---
        # Update non-existent entity
        non_existent_result = self.db.update_entity(column_name, "NonExistentEntity", update_data)
        self.assertFalse(non_existent_result["success"])
        self.assertEqual(non_existent_result["message"], "Entity not found or update failed in storage.")

        # Update entity in non-existent column
        non_existent_col_result = self.db.update_entity("NonExistentColumn", entity_name, update_data)
        self.assertFalse(non_existent_col_result["success"])
        # This message might also be "Entity not found..." because the column check happens in storage first.
        # Or it could be a different message if core.py checks column existence before calling storage.
        # Based on current core.py, it will try to update in-memory first if storage says success.
        # But storage.update_entity will return False for non-existent column.
        self.assertEqual(non_existent_col_result["message"], "Entity not found or update failed in storage.")

        # Update entity with data not containing properties, relationships, or location (should still update timestamp)
        time.sleep(0.01)
        empty_payload_update = {"other_field": "some_value"} # This field will be filtered out by core.py
        update_result_empty_payload = self.db.update_entity(column_name, entity_name, empty_payload_update)
        self.assertTrue(update_result_empty_payload["success"], f"Update with empty payload failed: {update_result_empty_payload.get('message')}")

        raw_frame_in_cols_empty_payload = None
        for frame in self.db.columns[column_name]["frames"]:
            if frame["name"] == entity_name:
                raw_frame_in_cols_empty_payload = frame
                break
        self.assertIsNotNone(raw_frame_in_cols_empty_payload)
        # Check that updated_at changed from the one after partial_update
        self.assertGreater(raw_frame_in_cols_empty_payload["updated_at"], raw_frame_in_cols_partial["updated_at"])
        # And other data remains from previous (partial) update
        self.assertEqual(raw_frame_in_cols_empty_payload["location"]["room"], "Main Hall")


if __name__ == "__main__":
    unittest.main()
