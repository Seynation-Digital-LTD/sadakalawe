"""Branch rules in one place.

Staff work at their own branch. Admins (and staff given "view_all_branches")
can see every branch; only admins can act for another branch.
"""
from flask_login import current_user


def sees_all_branches():
    return (current_user.is_admin or current_user.can('view_all_branches')
            or not current_user.branch_id)


def can_see_branch(branch_id):
    return sees_all_branches() or branch_id == current_user.branch_id


def own_branch(requested=None):
    """Branch to act for: staff always get their own, admins get what they picked."""
    if not current_user.is_admin and current_user.branch_id:
        return current_user.branch_id
    try:
        return int(requested)
    except (TypeError, ValueError):
        return None
