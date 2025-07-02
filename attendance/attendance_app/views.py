from django.shortcuts import render
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Section, Student, Attendance
from .serializers import SectionSerializer, StudentSerializer, AttendanceSerializer
import cv2
import pytesseract
import re
from datetime import datetime
import os
from django.conf import settings
from django.core.files.storage import default_storage
from openpyxl import Workbook
from django.http import HttpResponse
from rest_framework.permissions import AllowAny

def preprocess_image(image_path):
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError("Failed to load image")
    # Use adaptive thresholding for better text detection on varied backgrounds
    img = cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
    # Remove median blur to preserve text clarity
    return img

def extract_roll_numbers(image_path):
    img = preprocess_image(image_path)
    # Test different PSM modes (e.g., 4 for single column, 11 for sparse text)
    text = pytesseract.image_to_string(img, config='--psm 4')
    # Enhanced regex to match full roll numbers (e.g., 2411CS010178) or partial numbers
    roll_numbers = re.findall(r'\b\d+[A-Za-z]{2}\d{6}\b|\b\d{3,10}\b', text)  # Matches 2411CS010178 or 3-10 digits
    return set(roll_numbers)

class SectionViewSet(viewsets.ModelViewSet):
    queryset = Section.objects.all()
    serializer_class = SectionSerializer
    permission_classes = [AllowAny]

class StudentViewSet(viewsets.ModelViewSet):
    queryset = Student.objects.all()
    serializer_class = StudentSerializer
    permission_classes = [AllowAny]

class AttendanceViewSet(viewsets.ModelViewSet):
    queryset = Attendance.objects.all()
    serializer_class = AttendanceSerializer
    permission_classes = [AllowAny]

    @action(detail=True, methods=['post'], url_path='upload')
    def upload_attendance(self, request, pk=None):
        try:
            section = Section.objects.get(pk=pk)
            file = request.FILES.get('file')
            if not file:
                return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)

            file_path = default_storage.save(os.path.join('uploads', file.name), file)
            full_path = os.path.join(default_storage.location, file_path)

            if not default_storage.exists(file_path):
                return Response({'error': 'Failed to save file'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            roll_numbers = extract_roll_numbers(full_path)
            if not roll_numbers:
                return Response({'error': 'No roll numbers detected in the image. Try a different PSM mode (e.g., --psm 11) or check image clarity.'}, status=status.HTTP_400_BAD_REQUEST)

            date = datetime.now().date()
            students = Student.objects.filter(section=section)
            created_attendances = []

            for student in students:
                partial_roll = student.roll_number[-3:]  # Match last 3 digits
                status_text = 'Present' if partial_roll in roll_numbers else 'Absent'
                attendance, created = Attendance.objects.get_or_create(
                    student=student,
                    date=date,
                    defaults={'status': status_text}
                )
                if created:
                    created_attendances.append(attendance)

            if not created_attendances:
                return Response({'message': 'No new attendance records created'}, status=status.HTTP_200_OK)

            serializer = self.get_serializer(created_attendances, many=True)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        except Section.DoesNotExist:
            return Response({'error': 'Section not found'}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': f'Internal server error: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'], url_path='export')
    def export_attendance(self, request, pk=None):
        section = Section.objects.get(pk=pk)
        date = request.query_params.get('date', str(datetime.now().date()))
        try:
            date = datetime.strptime(date, '%Y-%m-%d').date()
        except ValueError:
            return Response({'error': 'Invalid date format'}, status=status.HTTP_400_BAD_REQUEST)

        attendances = Attendance.objects.filter(student__section=section, date=date)

        wb = Workbook()
        ws = wb.active
        ws.title = f"Attendance_{section.section_name}_{date}"
        ws.append(['Roll Number', 'Name', 'Date', 'Status'])

        for attendance in attendances:
            ws.append([
                attendance.student.roll_number,
                attendance.student.name,
                str(attendance.date),
                attendance.status
            ])

        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename=attendance_{section.section_name}_{date}.xlsx'
        wb.save(response)
        return response

def index(request):
    return render(request, 'index.html')