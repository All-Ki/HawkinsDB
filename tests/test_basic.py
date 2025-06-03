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

    def test_add_or_update_entity(self):
        """Test the add_or_update_entity functionality."""
        entity_name = "TestAddOrUpdate"
        entity_name_lower = entity_name.lower()
        column_name = "Episodic" # Requires timestamp for add_entity validation

        # 1. Test "add" functionality
        initial_properties = {"value": 100, "status": "initial", "timestamp": datetime.now().isoformat()}
        entity_data_initial = {
            "name": entity_name,
            "column": column_name,
            "properties": initial_properties,
            "relationships": {"related_to": "something"},
            "location": {"source": "test_add"}
        }
        
        result_add = self.db.add_or_update_entity(entity_data_initial)
        self.assertTrue(result_add.get("success"), f"Add failed: {result_add.get('message')}")
        self.assertEqual(result_add.get("action"), "added")
        self.assertEqual(result_add.get("entity_name"), entity_name_lower)
        self.assertIn(f"Successfully added {column_name} memory: {entity_name}", result_add.get("message",""))

        # Verify by querying
        queried_add_frames = self.db.query_frames(entity_name)
        self.assertIn(column_name, queried_add_frames)
        frame_after_add = queried_add_frames[column_name]
        self.assertEqual(frame_after_add.properties["value"][0].value, 100)
        self.assertEqual(frame_after_add.properties["status"][0].value, "initial")
        self.assertEqual(frame_after_add.relationships["related_to"][0].value, "something")
        self.assertEqual(frame_after_add.location["source"], "test_add")
        
        # Store created_at for later comparison with updated_at
        raw_frame_after_add = None
        for frame_dict in self.db.columns[column_name]["frames"]:
            if frame_dict["name"] == entity_name:
                raw_frame_after_add = frame_dict
                break
        self.assertIsNotNone(raw_frame_after_add)
        created_at_timestamp = raw_frame_after_add.get("created_at")
        self.assertIsNotNone(created_at_timestamp)
        # In add_entity, updated_at might be same as created_at initially by SQLite default
        # or by explicit setting in add_entity if it were to set it.
        # For SQLiteStorage, update_entity always sets updated_at, add_entity relies on table defaults or explicit values.
        # The core add_entity doesn't explicitly set created_at/updated_at, it relies on storage or _save.
        # _save in JSONStorage sets them if not present. SQLiteStorage sets them on insert.
        # So, after add, created_at and updated_at from storage should exist.
        
        # 2. Test "update" functionality
        time.sleep(0.01) # Ensure timestamp difference for updated_at
        updated_properties = {"value": 200, "status": "updated", "new_prop": "added_during_update"}
        # Note: 'timestamp' is not in updated_properties, so it will be removed if properties are overwritten.
        entity_data_updated = {
            "name": entity_name, # Same name
            "column": column_name, # Same column
            "properties": updated_properties,
            "relationships": {"related_to": "something_else", "linked_to": "another_item"}, # Modified and new relationship
            # Location is not provided, so it should remain as is from the add, if update_entity logic is partial for top-level keys
            # However, add_or_update_entity prepares a payload of specific keys: properties, relationships, location.
            # If a key is missing in `entity_data_updated` (e.g. location), it won't be in `update_payload`.
            # Then `update_entity` in core.py won't update it in memory if not in its `data` arg.
            # And `SQLiteStorage.update_entity` won't update it in DB if not in its `data` arg.
            # So, location should persist.
        }

        result_update = self.db.add_or_update_entity(entity_data_updated)
        self.assertTrue(result_update.get("success"), f"Update failed: {result_update.get('message')}")
        self.assertEqual(result_update.get("action"), "updated")
        self.assertEqual(result_update.get("entity_name"), entity_name) # update_entity returns original case name
        self.assertIn(f"Successfully updated {column_name} memory: {entity_name}", result_update.get("message",""))

        # Verify by querying again
        queried_update_frames = self.db.query_frames(entity_name)
        self.assertIn(column_name, queried_update_frames)
        frame_after_update = queried_update_frames[column_name]
        self.assertEqual(frame_after_update.properties["value"][0].value, 200)
        self.assertEqual(frame_after_update.properties["status"][0].value, "updated")
        self.assertEqual(frame_after_update.properties["new_prop"][0].value, "added_during_update")
        self.assertNotIn("timestamp", frame_after_update.properties) # As it was not in updated_properties

        self.assertEqual(frame_after_update.relationships["related_to"][0].value, "something_else")
        self.assertEqual(frame_after_update.relationships["linked_to"][0].value, "another_item")
        self.assertEqual(frame_after_update.location["source"], "test_add") # Location should persist

        # Verify updated_at timestamp
        raw_frame_after_update = None
        for frame_dict_upd in self.db.columns[column_name]["frames"]:
            if frame_dict_upd["name"] == entity_name:
                raw_frame_after_update = frame_dict_upd
                break
        self.assertIsNotNone(raw_frame_after_update)
        self.assertIsNotNone(raw_frame_after_update.get("updated_at"))
        self.assertGreater(raw_frame_after_update["updated_at"], created_at_timestamp)
        # Also check against the updated_at right after add, if they were different
        if raw_frame_after_add.get("updated_at") and raw_frame_after_add["updated_at"] > created_at_timestamp:
             self.assertGreater(raw_frame_after_update["updated_at"], raw_frame_after_add["updated_at"])


        # 3. Test missing name
        result_missing_name = self.db.add_or_update_entity({"column": "Semantic", "properties": {"key": "value"}})
        self.assertFalse(result_missing_name.get("success"))
        self.assertEqual(result_missing_name.get("action"), "error")
        self.assertEqual(result_missing_name.get("message"), "Entity name is required.")

        # 4. Test EntityValidationError handling (for Episodic missing timestamp on add)
        bad_episodic_data = {"name": "BadEpisodic", "column": "Episodic", "properties": {"detail": "missing timestamp"}}
        result_validation_error = self.db.add_or_update_entity(bad_episodic_data)
        
        self.assertFalse(result_validation_error.get("success"))
        self.assertEqual(result_validation_error.get("action"), "error")
        self.assertIn("Validation error", result_validation_error.get("message", ""))
        self.assertIn("Episodic memories require a timestamp", result_validation_error.get("message", ""))

        # 5. Test update on a different column if name exists elsewhere (should still be an add)
        other_column_name = "Semantic"
        entity_data_other_column = {
            "name": entity_name, # Same name "TestAddOrUpdate"
            "column": other_column_name, # Different column "Semantic"
            "properties": {"feature": "column_test"}
        }
        result_add_other_col = self.db.add_or_update_entity(entity_data_other_column)
        self.assertTrue(result_add_other_col.get("success"), f"Add to other column failed: {result_add_other_col.get('message')}")
        self.assertEqual(result_add_other_col.get("action"), "added")
        self.assertEqual(result_add_other_col.get("entity_name"), entity_name_lower)
        self.assertIn(f"Successfully added {other_column_name} memory: {entity_name}", result_add_other_col.get("message",""))

        # Verify entity exists in both columns now
        queried_all_cols = self.db.query_frames(entity_name)
        self.assertIn(column_name, queried_all_cols) # Episodic
        self.assertIn(other_column_name, queried_all_cols) # Semantic
        self.assertEqual(queried_all_cols[other_column_name].properties["feature"][0].value, "column_test")
        self.assertEqual(queried_all_cols[column_name].properties["value"][0].value, 200) # From previous update


if __name__ == "__main__":
    unittest.main()
