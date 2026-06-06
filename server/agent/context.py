
import os
from dataclasses import dataclass
from pathlib import Path
from server.core.logger import logger

DATA_PATH = Path("./data")

@dataclass
class SessionContext:
    session_id: int
    
    def get_data_path(self):
        """
        Get session path with specified session ID. The directory will be created if the path is not existed.
        """
        path = DATA_PATH / str(self.session_id)
        if not os.path.exists(path):
            logger.debug("Creating directory %s", str(path))
            os.makedirs(path)
            
        return path
            