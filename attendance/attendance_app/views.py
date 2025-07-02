from django.shortcuts import render
from django.http import JsonResponse
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import AllowAny
from .models import Section, Student, AttendanceSession, Attendance
from .serializers import SectionSerializer, StudentSerializer, AttendanceSessionSerializer, AttendanceSerializer, ImageUploadSerializer
import cv2
import numpy as np
from PIL import Image
import pytesseract
import re
import os
from django.conf import settings
from django.db.models import Q

def index(request):
    try:
        return render(request, 'frontend/build/index.html')
    except Exception as e:
        return JsonResponse({'error': f'Failed to render index: {str(e)}'}, status=500)

class SectionViewSet(viewsets.ModelViewSet):
    queryset = Section.objects.all()
    serializer_class = SectionSerializer
    permission_classes = [AllowAny]

    def list(self, request, *args, **kwargs):
        try:
            queryset = self.get_queryset()
            serializer = self.get_serializer(queryset, many=True)
            return Response(serializer.data)
        except Exception as e:
            return Response({'error': str(e)}, status=500)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        try:
            if serializer.is_valid():
                self.perform_create(serializer)
                headers = self.get_success_headers(serializer.data)
                return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class StudentViewSet(viewsets.ModelViewSet):
    queryset = Student.objects.all()
    serializer_class = StudentSerializer

    @action(detail=False, methods=['get'])
    def by_section(self, request):
        section_id = request.query_params.get('section_id')
        if section_id:
            students = Student.objects.filter(section_id=section_id)
            serializer = self.get_serializer(students, many=True)
            return Response(serializer.data)
        return Response({'error': 'Section ID required'}, status=400)

class AttendanceViewSet(viewsets.ModelViewSet):
    queryset = Attendance.objects.all()
    serializer_class = AttendanceSerializer
    parser_classes = (MultiPartParser, FormParser)

    @action(detail=False, methods=['post'])
    def mark_by_image(self, request):
        serializer = ImageUploadSerializer(data=request.data)
        if serializer.is_valid():
            image = serializer.validated_data['image']
            session_id = serializer.validated_data['session_id']

            try:
                session = AttendanceSession.objects.get(id=session_id)
                roll_numbers = self.extract_roll_numbers_from_image(image)
                print(f"Detected roll numbers: {roll_numbers}")  # Debug output

                marked_count = 0
                for roll_number in roll_numbers:
                    try:
                        # Try exact match first
                        student = Student.objects.get(roll_number=roll_number, section=session.section)
                        attendance, created = Attendance.objects.get_or_create(
                            session=session,
                            student=student,
                            defaults={'is_present': True, 'image': image}
                        )
                        if not created:
                            attendance.is_present = True
                            attendance.save()
                        marked_count += 1
                        print(f"Marked {student.name} (Roll: {roll_number}) - Exact match")
                    except Student.DoesNotExist:
                        # Fallback: Match by last three digits (e.g., '178' for '2411CS010178')
                        if len(roll_number) >= 3:
                            last_three = roll_number[-3:]
                            students = Student.objects.filter(
                                section=session.section,
                                roll_number__endswith=last_three
                            )
                            if students.exists():
                                for student in students:
                                    attendance, created = Attendance.objects.get_or_create(
                                        session=session,
                                        student=student,
                                        defaults={'is_present': True, 'image': image}
                                    )
                                    if not created:
                                        attendance.is_present = True
                                        attendance.save()
                                    marked_count += 1
                                    print(f"Marked {student.name} (Roll: {student.roll_number}) - Last 3 digits match: {last_three}")
                            else:
                                print(f"No student found for last 3 digits: {last_three}")
                        else:
                            print(f"Roll number {roll_number} too short for last 3 digits match")

                return Response({
                    'success': True,
                    'message': f'Marked attendance for {marked_count} students',
                    'roll_numbers_found': roll_numbers
                })

            except AttendanceSession.DoesNotExist:
                return Response({'error': 'Session not found'}, status=404)
            except Exception as e:
                return Response({'error': str(e)}, status=500)

        return Response(serializer.errors, status=400)

    def extract_roll_numbers_from_image(self, image_file):
        # Save uploaded image temporarily
        image_path = os.path.join(settings.MEDIA_ROOT, 'temp_' + image_file.name)
        print(f"Attempting to save image to: {image_path}")  # Debug
        try:
            with open(image_path, 'wb+') as destination:
                for chunk in image_file.chunks():
                    destination.write(chunk)
            print(f"Image saved successfully at: {image_path}")
        except Exception as e:
            print(f"Error saving image: {e}")
            return []

        try:
            # Load and preprocess image
            print(f"Loading image: {image_path}")
            image = cv2.imread(image_path)
            if image is None:
                print("Failed to load image with cv2.imread")
                return []
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            print("Image converted to grayscale")

            # Apply preprocessing
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
            gray = clahe.apply(gray)
            print("CLAHE applied")

            # Noise removal
            gray = cv2.medianBlur(gray, 3)
            print("Noise removal applied")

            # Thresholding
            _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            print("Thresholding applied")

            # OCR
            print("Performing OCR...")
            text = pytesseract.image_to_string(thresh, config='--psm 6')
            print(f"OCR text output: {text}")

            # Extract roll numbers using regex, including standalone numbers like '178'
            roll_numbers = []
            patterns = [
                r'\b\d{2}[A-Z]\d{2}[A-Z]\d{4}\b',  # Pattern: 22B01A1234
                r'\b[A-Z]\d{2}[A-Z]\d{2}[A-Z]\d{3}\b',  # Pattern: A22B01C123
                r'\b\d{4}[A-Z]\d{4}\b',  # Pattern: 2022A1234
                r'\b[A-Z]{2}\d{2}[A-Z]\d{4}\b',  # Pattern: CS22A1234
                r'\b\d{2}[A-Z]\d{6}\b',  # Pattern: 22A123456
                r'\b\d{3}\b'  # Added pattern for standalone 3-digit numbers like '178'
            ]

            for pattern in patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                roll_numbers.extend([match.upper() for match in matches])

            # Remove duplicates
            roll_numbers = list(set(roll_numbers))

            return roll_numbers

        except Exception as e:
            print(f"Error processing image: {e}")
            return []
        finally:
            # Clean up temporary file
            if os.path.exists(image_path):
                os.remove(image_path)

    @action(detail=False, methods=['get'])
    def session_attendance(self, request):
        session_id = request.query_params.get('section_id')
        if session_id:
            try:
                session = AttendanceSession.objects.get(id=session_id)
                students = Student.objects.filter(section=session.section)
                attendance_data = []

                for student in students:
                    try:
                        attendance = Attendance.objects.get(session=session, student=student)
                        attendance_data.append({
                            'student_id': student.id,
                            'roll_number': student.roll_number,
                            'name': student.name,
                            'is_present': attendance.is_present,
                            'marked_at': attendance.marked_at
                        })
                    except Attendance.DoesNotExist:
                        attendance_data.append({
                            'student_id': student.id,
                            'roll_number': student.roll_number,
                            'name': student.name,
                            'is_present': False,
                            'marked_at': None
                        })

                return Response(attendance_data)
            except AttendanceSession.DoesNotExist:
                return Response({'error': 'Session not found'}, status=404)

        return Response({'error': 'Session ID required'}, status=400)

class AttendanceSessionViewSet(viewsets.ModelViewSet):
    queryset = AttendanceSession.objects.all()
    serializer_class = AttendanceSessionSerializer

    def list(self, request, *args, **kwargs):
        try:
            queryset = self.get_queryset()
            serializer = self.get_serializer(queryset, many=True)
            return Response(serializer.data)
        except Exception as e:
            return Response({'error': str(e)}, status=500)

    @action(detail=False, methods=['get'])
    def active_sessions(self, request):
        sessions = AttendanceSession.objects.filter(is_active=True)
        serializer = self.get_serializer(sessions, many=True)
        return Response(serializer.data)