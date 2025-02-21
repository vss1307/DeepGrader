from flask import Flask, render_template, request, redirect, url_for, session, flash
from pymongo import MongoClient
import bcrypt
import os
from functools import wraps
import random
import string
from datetime import datetime

app = Flask(__name__, 
    static_folder='static',  # Make sure this matches your folder name
    static_url_path='/static'
)
app.secret_key = os.urandom(24)

# MongoDB Connection
client = MongoClient('mongodb://localhost:27017/')
db = client['user_auth_db']
users_collection = db['users']
classrooms_collection = db['classrooms']

# Create indexes
users_collection.create_index("username", unique=True)
classrooms_collection.create_index("code", unique=True)

# Generate unique classroom code
def generate_classroom_code():
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not classrooms_collection.find_one({'code': code}):
            return code

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            flash('Please login first')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']
        role = request.form['role']
        
        existing_user = users_collection.find_one({'username': username})
        if existing_user:
            flash('Username already exists')
            return redirect(url_for('signup'))
        
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        
        # Generate classroom code and create classroom for teachers during signup
        if role == 'teacher':
            classroom_code = generate_classroom_code()
            classroom_name = f"{username}'s Classroom"  # Create classroom name
            
            # Create the classroom document
            classroom_data = {
                'code': classroom_code,
                'name': classroom_name,
                'teacher': username,
                'students': [],
                'assignments': []
            }
            classrooms_collection.insert_one(classroom_data)
            
            # Include classroom code in user data for teachers
            user_data = {
                'username': username,
                'password': hashed_password,
                'email': email,
                'role': role,
                'classroom_code': classroom_code,
                'classroom_name': classroom_name
            }
        else:
            # Regular user data for students
            user_data = {
                'username': username,
                'password': hashed_password,
                'email': email,
                'role': role
            }
        
        users_collection.insert_one(user_data)
        flash('Registration successful! Please login.')
        return redirect(url_for('login'))
    
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = users_collection.find_one({'username': username})
        
        if user and bcrypt.checkpw(password.encode('utf-8'), user['password']):
            session['username'] = username
            session['role'] = user['role']
            
            flash(f'Welcome back, {username}!')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password')
    
    return render_template('login.html')

@app.route('/dashboard')
@login_required
def dashboard():
    user = users_collection.find_one({'username': session['username']})
    if user['role'] == 'teacher':
        classroom = classrooms_collection.find_one({'teacher': session['username']})
        return render_template('dashboard.html', user=user, classroom=classroom)
    else:
        joined_classrooms = list(classrooms_collection.find(
            {'students': session['username']}
        ))
        return render_template('dashboard.html', user=user, joined_classrooms=joined_classrooms)


@app.route('/join_classroom', methods=['GET', 'POST'])
@login_required
def join_classroom():
    if session['role'] != 'student':
        flash('Only students can join classrooms')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        code = request.form['classroom_code']
        classroom = classrooms_collection.find_one({'code': code})
        
        if not classroom:
            flash('Invalid classroom code')
            return redirect(url_for('join_classroom'))
        
        if session['username'] in classroom['students']:
            flash('You are already in this classroom')
            return redirect(url_for('dashboard'))
        
        classrooms_collection.update_one(
            {'code': code},
            {'$push': {'students': session['username']}}
        )
        
        flash('Successfully joined classroom!')
        return redirect(url_for('dashboard'))
    
    return render_template('join_classroom.html')



@app.route('/classroom/<classroom_code>')
@login_required
def view_classroom(classroom_code):
    classroom = classrooms_collection.find_one({'code': classroom_code})
    if not classroom:
        flash('Classroom not found')
        return redirect(url_for('dashboard'))
    
    # Check if user has access to this classroom
    if session['role'] == 'student' and session['username'] not in classroom['students']:
        flash('You do not have access to this classroom')
        return redirect(url_for('dashboard'))
    elif session['role'] == 'teacher' and session['username'] != classroom['teacher']:
        flash('You do not have access to this classroom')
        return redirect(url_for('dashboard'))
    
    return render_template('classroom.html', classroom=classroom, user={'role': session['role']})

import fitz  # PyMuPDF for PDF processing

def extract_text_from_pdf(pdf_file):
    try:
        doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text()
        return text.strip()
    except Exception as e:
        print(f"Error extracting text from PDF: {str(e)}")
        return None

@app.route('/classroom/<classroom_code>/add_assignment', methods=['GET', 'POST'])
@login_required
def add_assignment(classroom_code):
    if session['role'] != 'teacher':
        flash('Only teachers can add assignments')
        return redirect(url_for('dashboard'))
    
    classroom = classrooms_collection.find_one({
        'code': classroom_code,
        'teacher': session['username']
    })
    
    if not classroom:
        flash('Classroom not found')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        title = request.form['title']
        questions_type = request.form['questions_type']
        answers_type = request.form['answers_type']
        
        # Handle questions
        if questions_type == 'text':
            questions = request.form['questions_text']
        else:
            questions_pdf = request.files['questions_pdf']
            questions = extract_text_from_pdf(questions_pdf)
            if not questions:
                flash('Error extracting text from questions PDF')
                return redirect(url_for('add_assignment', classroom_code=classroom_code))
        
        # Handle model answers
        if answers_type == 'text':
            model_answers = request.form['answers_text']
        else:
            answers_pdf = request.files['answers_pdf']
            model_answers = extract_text_from_pdf(answers_pdf)
            if not model_answers:
                flash('Error extracting text from answers PDF')
                return redirect(url_for('add_assignment', classroom_code=classroom_code))

        assignment = {
            'title': title,
            'questions': questions,
            'model_answers': model_answers,
            'date_added': datetime.now(),
            'submissions': {}
        }
        
        classrooms_collection.update_one(
            {'code': classroom_code},
            {'$push': {'assignments': assignment}}
        )
        
        flash('Assignment added successfully')
        return redirect(url_for('view_classroom', classroom_code=classroom_code))
    
    return render_template('add_assignment.html')

from mira_sdk import MiraClient, Flow
import os
import json


MIRA_API_KEY = os.getenv("MIRA_API_KEY")
client = MiraClient(config={"API_KEY": MIRA_API_KEY})



@app.route('/classroom/<classroom_code>/assignment/<int:assignment_id>/submit', methods=['GET', 'POST'])
@login_required
def submit_assignment(classroom_code, assignment_id):
    if session['role'] != 'student':
        flash('Only students can submit assignments')
        return redirect(url_for('dashboard'))
    
    classroom = classrooms_collection.find_one({'code': classroom_code})
    if not classroom or session['username'] not in classroom['students']:
        flash('Access denied')
        return redirect(url_for('dashboard'))
    
    try:
        assignment = classroom['assignments'][assignment_id]
    except IndexError:
        flash('Assignment not found')
        return redirect(url_for('view_classroom', classroom_code=classroom_code))
    
    # Check if student has already submitted
    if 'submissions' in assignment and session['username'] in assignment['submissions']:
        submission = assignment['submissions'][session['username']]
        return render_template('submit_assignment.html', 
                             assignment=assignment,
                             submitted_answer=submission['answer'],
                             grade=submission['grade'])
    
    if request.method == 'POST':
        answer_type = request.form['answer_type']
        
        try:
            # Handle student answer
            if answer_type == 'text':
                student_answer = request.form['answer_text']
            else:
                answer_pdf = request.files['answer_pdf']
                if not answer_pdf:
                    flash('No PDF file uploaded')
                    return render_template('submit_assignment.html', assignment=assignment)
                
                student_answer = extract_text_from_pdf(answer_pdf)
                if not student_answer:
                    flash('Error extracting text from PDF')
                    return render_template('submit_assignment.html', assignment=assignment)
                
                # Clean up the extracted text
                student_answer = student_answer.strip().replace('\n', ' ').replace('\r', '')
            
            print("Student Answer:", student_answer)  # Debug print
            
            # Prepare inputs for Mira API
            flow = Flow(source="autograder.yaml")
            input_dict = {
                "input1": assignment['questions'],
                "input2": assignment['model_answers'],
                "input3": student_answer
            }
            
            print("API Input:", input_dict)  # Debug print

            # Call Mira API
            response = client.flow.test(flow, input_dict)
            grade = response['result']
            
            print("API Response:", grade)  # Debug print
            
            # Store the submission and grade
            submission_data = {
                'answer': student_answer,
                'answer_type': answer_type,
                'grade': grade,
                'date_submitted': datetime.now()
            }
            
            # Update the assignment with the student's submission
            update_query = {
                'code': classroom_code,
                'assignments.' + str(assignment_id): {'$exists': True}
            }
            update_data = {
                '$set': {
                    f'assignments.{assignment_id}.submissions.{session["username"]}': submission_data
                }
            }
            classrooms_collection.update_one(update_query, update_data)
            
            return render_template('submit_assignment.html', 
                                 assignment=assignment,
                                 submitted_answer=student_answer,
                                 grade=grade)
            
        except Exception as e:
            print("Error details:", str(e))
            flash(f'Error during grading: {str(e)}')
            return render_template('submit_assignment.html', 
                                 assignment=assignment)
    
    return render_template('submit_assignment.html', assignment=assignment)


@app.route('/classroom/<classroom_code>/assignment/<int:assignment_id>/view')
@login_required
def view_submission(classroom_code, assignment_id):
    if session['role'] != 'student':
        flash('Access denied')
        return redirect(url_for('dashboard'))
    
    classroom = classrooms_collection.find_one({'code': classroom_code})
    if not classroom or session['username'] not in classroom['students']:
        flash('Access denied')
        return redirect(url_for('dashboard'))
    
    try:
        assignment = classroom['assignments'][assignment_id]
        if 'submissions' not in assignment or session['username'] not in assignment['submissions']:
            flash('No submission found')
            return redirect(url_for('view_classroom', classroom_code=classroom_code))
        
        submission = assignment['submissions'][session['username']]
        return render_template('view_submission.html',
                                
                             assignment=assignment,
                             submission=submission)
    
    except IndexError:
        flash('Assignment not found')
        return redirect(url_for('view_classroom', classroom_code=classroom_code))

@app.route('/classroom/<classroom_code>/assignment/<int:assignment_id>/submissions')
@login_required
def view_all_submissions(classroom_code, assignment_id):
    if session['role'] != 'teacher':
        flash('Access denied')
        return redirect(url_for('dashboard'))
    
    classroom = classrooms_collection.find_one({
        'code': classroom_code,
        'teacher': session['username']
    })
    
    if not classroom:
        flash('Classroom not found')
        return redirect(url_for('dashboard'))
    
    try:
        assignment = classroom['assignments'][assignment_id]
        return render_template('view_all_submissions.html', 
                             classroom=classroom,
                             assignment=assignment,
                             assignment_id=assignment_id)
    except IndexError:
        flash('Assignment not found')
        return redirect(url_for('view_classroom', classroom_code=classroom_code))

@app.route('/classroom/<classroom_code>/assignment/<int:assignment_id>/submission/<student_username>')
@login_required
def view_student_submission(classroom_code, assignment_id, student_username):
    if session['role'] != 'teacher':
        flash('Access denied')
        return redirect(url_for('dashboard'))
    
    classroom = classrooms_collection.find_one({
        'code': classroom_code,
        'teacher': session['username']
    })
    
    if not classroom:
        flash('Classroom not found')
        return redirect(url_for('dashboard'))
    
    try:
        assignment = classroom['assignments'][assignment_id]
        if student_username not in assignment['submissions']:
            flash('Submission not found')
            return redirect(url_for('view_all_submissions', 
                                  classroom_code=classroom_code, 
                                  assignment_id=assignment_id))
        
        submission = assignment['submissions'][student_username]
        return render_template('view_submission.html', 
                             student_username=student_username,
                             assignment=assignment,
                             submission=submission)
    except IndexError:
        flash('Assignment not found')
        return redirect(url_for('view_classroom', classroom_code=classroom_code))






@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out')
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=True, port=8080)
