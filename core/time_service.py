
import pytz
from datetime import datetime, timedelta

class TimeService:
    """
    Centralized timezone management enforcing Asia/Dubai for all operations.
    All timestamps, deadlines, and logs must use this service.
    """
    
    def __init__(self):
        self.timezone = pytz.timezone('Asia/Dubai')
    
    def now(self) -> datetime:
        """Get current time in Dubai timezone"""
        return datetime.now(self.timezone)
    
    def now_iso(self) -> str:
        """Get current time as ISO-8601 string in Dubai timezone"""
        return self.now().isoformat()
    
    def now_str(self, format_str: str = '%Y-%m-%d %H:%M:%S') -> str:
        """Get current time as formatted string in Dubai timezone"""
        return self.now().strftime(format_str)
    
    def localize(self, dt: datetime) -> datetime:
        """Localize a naive datetime to Dubai timezone"""
        if dt.tzinfo is None:
            return self.timezone.localize(dt)
        return dt.astimezone(self.timezone)
    
    def parse_iso(self, iso_string: str) -> datetime:
        """Parse ISO-8601 string to Dubai timezone datetime"""
        dt = datetime.fromisoformat(iso_string.replace('Z', '+00:00'))
        return dt.astimezone(self.timezone)
    
    def add_minutes(self, dt: datetime, minutes: int) -> datetime:
        """Add minutes to a datetime in Dubai timezone"""
        return dt + timedelta(minutes=minutes)
    
    def get_today_date(self) -> str:
        """Get today's date in Dubai timezone (YYYY-MM-DD)"""
        return self.now().strftime('%Y-%m-%d')
    
    def get_month_prefix(self) -> str:
        """Get current month prefix (YYYY-MM)"""
        return self.now().strftime('%Y-%m')

time_service = TimeService()
