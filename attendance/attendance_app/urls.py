from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import SectionViewSet, StudentViewSet, AttendanceViewSet

router = DefaultRouter()
router.register(r'sections', SectionViewSet)
router.register(r'students', StudentViewSet)
router.register(r'attendance', AttendanceViewSet)

urlpatterns = [
    path('', include(router.urls)),
]