"""Item endpoints."""

from fastapi import APIRouter, HTTPException
from typing import List

from server.schemas.items import ItemResponse, ItemCreate

router = APIRouter()

# In-memory storage for demo purposes
items_db = {}
next_item_id = 1


@router.get("", response_model=List[ItemResponse])
async def list_items():
    """List all items."""
    return list(items_db.values())


@router.get("/{item_id}", response_model=ItemResponse)
async def get_item(item_id: int):
    """Get a specific item by ID."""
    item = items_db.get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    return item


@router.post("", response_model=ItemResponse)
async def create_item(item: ItemCreate):
    """Create a new item."""
    global next_item_id
    new_item = ItemResponse(id=next_item_id, **item.dict())
    items_db[next_item_id] = new_item
    next_item_id += 1
    
    return new_item


@router.put("/{item_id}", response_model=ItemResponse)
async def update_item(item_id: int, item: ItemCreate):
    """Update an existing item."""
    if item_id not in items_db:
        raise HTTPException(status_code=404, detail="Item not found")
    
    updated_item = ItemResponse(id=item_id, **item.dict())
    items_db[item_id] = updated_item
    
    return updated_item


@router.delete("/{item_id}")
async def delete_item(item_id: int):
    """Delete an item."""
    if item_id not in items_db:
        raise HTTPException(status_code=404, detail="Item not found")
    
    del items_db[item_id]
    return {"message": "Item deleted successfully"}
