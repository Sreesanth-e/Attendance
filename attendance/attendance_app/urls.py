from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import SectionViewSet, StudentViewSet, AttendanceViewSet, AttendanceSessionViewSet

router = DefaultRouter()
router.register(r'sections', SectionViewSet)
router.register(r'students', StudentViewSet)
router.register(r'attendance', AttendanceViewSet)
router.register(r'sessions', AttendanceSessionViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('attendance/mark_by_image/', AttendanceViewSet.as_view({'post': 'mark_by_image'}), name='mark_attendance_by_image'),
    path('attendance/session_attendance/', AttendanceViewSet.as_view({'get': 'session_attendance'}), name='session_attendance'),
    path('sessions/active_sessions/', AttendanceSessionViewSet.as_view({'get': 'active_sessions'}), name='active_sessions'),
]