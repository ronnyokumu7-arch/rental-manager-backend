from fastapi import Depends
from app.dependencies.auth import get_current_user
from app.models.users import User, UserRole
from app.core.errors import AuthorizationError

def require_role(allowed_roles: list[UserRole]):
    """
    A dependency factory that returns a dependency function 
    to check the current user's role.
    """
    def dependency(current_user: User = Depends(get_current_user)):
        if current_user.role not in allowed_roles:
            raise AuthorizationError()
        return current_user
    
    return dependency
