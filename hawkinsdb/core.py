"""Core functionality for HawkinsDB."""
import os
import json
import time
import logging
from datetime import datetime
from pathlib import Path
from .base import PropertyCandidate, ReferenceFrame, CorticalColumn

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from filelock import FileLock
except ImportError:
    logger.warning("FileLock not available, using dummy implementation")
    class FileLock:
        def __init__(self, *args): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass

class EntityValidationError(Exception):
    """Raised when entity validation fails."""
    pass

# Make EntityValidationError available at module level
__all__ = ['HawkinsDB', 'JSONStorage', 'EntityValidationError']

# Import storage backends
from .storage.sqlite import SQLiteStorage
# Ensure SQLiteStorage is available by default
if not SQLiteStorage:
    logger.error("Failed to import SQLiteStorage. Please check your installation.")
    raise ImportError("SQLiteStorage module is required but not available")

class JSONStorage:
    """Handles persistence of the HawkinsDB data in JSON format."""
    def __init__(self, path):
        self.path = Path(path)
        self.lock = FileLock(str(self.path) + ".lock")

    def initialize(self):
        if not self.path.exists():
            self._write_data({"columns": []})

    def cleanup(self):
        pass

    def _read_data(self):
        if not self.path.exists():
            return {"columns": []}
        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write_data(self, data):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    def load_columns(self):
        with self.lock:
            data = self._read_data()
            return data.get("columns", [])

    def save_columns(self, columns):
        with self.lock:
            data = {"columns": columns}
            self._write_data(data)

class HawkinsDB:
    """Main database interface."""
    
    # Make EntityValidationError accessible via the class
    EntityValidationError = EntityValidationError
    def __init__(self, storage=None, db_path=None, storage_type='sqlite'):
        if storage is None:
            if storage_type == 'sqlite':
                db_path = db_path or "hawkins_memory.db"
                self.storage = SQLiteStorage(db_path=db_path)
            elif storage_type == 'json':
                db_path = db_path or "hawkins_db.json"
                self.storage = JSONStorage(path=db_path)
            else:
                raise ValueError(f"Unsupported storage type: {storage_type}")
        else:
            self.storage = storage
        
        self.storage.initialize()
        self.columns = {}
        self._load_columns()
        self._build_indexes()
        self._initialize_memory_types()

    def _load_columns(self):
        columns = self.storage.load_columns()
        self.columns = {c["name"]: c for c in columns}

    def _build_indexes(self):
        self.name_index = {}
        for col_name, col in self.columns.items():
            for f in col["frames"]:
                name = f["name"].lower()
                if name not in self.name_index:
                    self.name_index[name] = []
                self.name_index[name].append((col_name, f))

    def _initialize_memory_types(self):
        for memory_type in ["Semantic", "Episodic", "Procedural"]:
            if memory_type not in self.columns:
                self.create_column(memory_type)

    def cleanup(self):
        if hasattr(self, 'storage'):
            self.storage.cleanup()

    def create_column(self, column_name):
        if column_name not in self.columns:
            self.columns[column_name] = {"name": column_name, "frames": []}
            self._save()

    def _save(self):
        self.storage.save_columns(list(self.columns.values()))
        
    def add_entity(self, data):
        """Add an entity with validation."""
        try:
            if not isinstance(data, dict):
                raise EntityValidationError("Entity data must be a dictionary")

            memory_type = data.get("column", "Semantic")
            name = data.get("name")
            
            if not name:
                raise EntityValidationError("Entity name is required")

            # Validate required fields based on memory type
            if memory_type == "Episodic":
                if "properties" not in data or "timestamp" not in data["properties"]:
                    raise EntityValidationError("Episodic memories require a timestamp")
                    
            elif memory_type == "Procedural":
                if "properties" not in data or "steps" not in data["properties"]:
                    raise EntityValidationError("Procedural memories require steps")
                
            properties = data.get("properties", {})
            relationships = data.get("relationships", {})
            
            frame = {
                "name": name,
                "properties": properties,
                "relationships": relationships,
                "location": data.get("location", {}),
                "history": []
            }
            
            if memory_type not in self.columns:
                self.create_column(memory_type)
                
            column = self.columns[memory_type]
            column["frames"].append(frame)
            name = name.lower()
            if name not in self.name_index:
                self.name_index[name] = []
            self.name_index[name].append((memory_type, frame))
            
            self._save()
            
            return {
                "success": True,
                "entity_name": name,
                "message": f"Successfully added {memory_type} memory: {name}"
            }
            
        except EntityValidationError as e:
            logger.error(f"Validation error: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Error adding entity: {str(e)}")
            return {
                "success": False,
                "message": str(e)
            }

    def query_frames(self, name):
        """Query frames by name and return dictionary of frames by column."""
        try:
            name = name.lower()
            frames = self.name_index.get(name, [])
            result = {}
            for column_name, frame_data in frames:
                if column_name not in result:
                    try:
                        # Always convert to ReferenceFrame
                        result[column_name] = ReferenceFrame.from_dict(frame_data)
                    except Exception as frame_error:
                        logger.error(f"Error converting frame data: {str(frame_error)}")
                        continue
            return result
        except Exception as e:
            logger.error(f"Error querying frames: {str(e)}")
            return {}

    def list_entities(self):
        try:
            return sorted(list(self.name_index.keys()))
        except Exception:
            return []

    def update_entity(self, column_name: str, frame_name: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an entity in storage and in-memory."""
        logger.info(f"Attempting to update entity '{frame_name}' in column '{column_name}' with data: {data}")

        # Filter data to only include allowed frame attributes for storage update
        allowed_storage_keys = {'properties', 'relationships', 'location'}
        storage_data = {k: v for k, v in data.items() if k in allowed_storage_keys}

        if not storage_data:
            logger.warning(f"No valid fields (properties, relationships, location) provided for updating entity '{frame_name}'.")
            # Even if no direct attributes are updated, the storage method might update 'updated_at'
            # Proceed to call storage.update_entity to ensure 'updated_at' is handled.

        try:
            update_successful = self.storage.update_entity(column_name, frame_name, storage_data)

            if update_successful:
                # Update in-memory self.columns
                if column_name in self.columns:
                    column_data = self.columns[column_name]
                    updated_frame_in_memory = False
                    for i, frame in enumerate(column_data.get("frames", [])):
                        if frame["name"] == frame_name:
                            if 'properties' in data:
                                frame['properties'] = data['properties']
                            if 'relationships' in data:
                                frame['relationships'] = data['relationships']
                            if 'location' in data:
                                frame['location'] = data['location']
                            frame['updated_at'] = datetime.now().isoformat() # Update timestamp
                            column_data["frames"][i] = frame
                            updated_frame_in_memory = True
                            logger.info(f"In-memory frame '{frame_name}' in column '{column_name}' updated.")
                            break
                    
                    if not updated_frame_in_memory:
                        logger.warning(f"Frame '{frame_name}' not found in-memory in column '{column_name}' for update, though storage succeeded.")

                    # Update in-memory self.name_index
                    frame_name_lower = frame_name.lower()
                    if frame_name_lower in self.name_index:
                        updated_frame_in_index = False
                        for i, (col_name_idx, frame_idx) in enumerate(self.name_index[frame_name_lower]):
                            if col_name_idx == column_name and frame_idx["name"] == frame_name:
                                if 'properties' in data:
                                    frame_idx['properties'] = data['properties']
                                if 'relationships' in data:
                                    frame_idx['relationships'] = data['relationships']
                                if 'location' in data:
                                    frame_idx['location'] = data['location']
                                frame_idx['updated_at'] = datetime.now().isoformat() # Update timestamp
                                self.name_index[frame_name_lower][i] = (col_name_idx, frame_idx)
                                updated_frame_in_index = True
                                logger.info(f"In-memory name_index for '{frame_name}' updated.")
                                break
                        if not updated_frame_in_index:
                             logger.warning(f"Frame '{frame_name}' not found in-memory name_index for update, though storage succeeded and column was updated.")
                    else:
                        logger.warning(f"Frame '{frame_name}' not found in name_index at all.")

                else:
                    logger.warning(f"Column '{column_name}' not found in-memory for updating frame '{frame_name}', though storage succeeded.")

                # self._save() # Decided against calling this as per reasoning in plan
                logger.info(f"Entity '{frame_name}' in column '{column_name}' updated successfully in storage and in-memory.")
                return {"success": True, "message": "Entity updated successfully."}
            else:
                logger.warning(f"Storage update failed for entity '{frame_name}' in column '{column_name}'.")
                return {"success": False, "message": "Entity not found or update failed in storage."}

        except Exception as e:
            logger.error(f"Error during entity update for '{frame_name}' in '{column_name}': {str(e)}")
            return {"success": False, "message": f"An unexpected error occurred: {str(e)}"}
