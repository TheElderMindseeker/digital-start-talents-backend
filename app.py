import os
from datetime import timedelta
from enum import Enum
from uuid import uuid4

from flask import Flask, request, abort, jsonify, send_from_directory
from flask_jwt_extended import JWTManager, jwt_required, create_access_token, get_jwt_identity
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship

MENTORSHIP_REQUIRES = 1_000

app = Flask(__name__, static_folder=None)
script_path = os.path.dirname(os.path.abspath(__file__))
default_db_path = os.path.join(script_path, 'hackathon.db')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('HACKATHON_DB_URL', f'sqlite:////{default_db_path}')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = 'secret-string'
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=7)
app.config['UPLOAD_FOLDER'] = os.path.join(script_path, 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
db = SQLAlchemy(app)
migrate = Migrate(app, db)
jwt = JWTManager(app)


class MentorshipState(Enum):
    not_enough_points = 'not_enough_points'
    uninitialized = 'uninitialized'
    waiting = 'waiting'
    mentored = 'mentored'


class Kid(db.Model):
    __tablename__ = 'kids'
    id = Column(Integer, primary_key=True)
    phone_number = Column(String(12), unique=True)
    account_id = Column(String(128), unique=True, nullable=False)
    name = Column(String(256), nullable=False)
    birth_date = Column(String(12), nullable=False)
    goal = Column(String(1024))
    points = Column(Integer, nullable=False, default=100)
    avatar = Column(String(512))
    mentorship = Column(SQLEnum(MentorshipState), nullable=False, default=MentorshipState.not_enough_points)
    tasks = relationship('Task')
    interests = relationship('Tag', secondary='interests')
    likes = relationship('Mentor', secondary='likes')


class Tag(db.Model):
    __tablename__ = 'tags'
    id = Column(Integer, primary_key=True)
    name = Column(String(64), unique=True, nullable=False)


class Mentor(db.Model):
    __tablename__ = 'mentors'
    id = Column(Integer, primary_key=True)
    name = Column(String(256), nullable=False)
    photo = Column(String(1024))
    position = Column(String(256), nullable=False)
    bio = Column(String(1024), nullable=False)
    expertises = relationship('Tag', secondary='expertises')


likes = db.Table(  # noqa
    'likes',
    Column('kid_id', Integer, ForeignKey('kids.id'), primary_key=True),
    Column('mentor_id', Integer, ForeignKey('mentors.id'), primary_key=True),
)


interests = db.Table(  # noqa
    'interests',
    Column('kid_id', Integer, ForeignKey('kids.id'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('tags.id'), primary_key=True),
)


expertises = db.Table(  # noqa
    'expertises',
    Column('mentor_id', Integer, ForeignKey('mentors.id'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('tags.id'), primary_key=True),
)


class Task(db.Model):
    __tablename__ = 'tasks'
    id = Column(Integer, primary_key=True)
    kid_id = Column(Integer, ForeignKey('kids.id'))
    text = Column(String(1024), nullable=False)
    order = Column(Integer, nullable=False)
    done = Column(Boolean, nullable=False, default=False)


class Proposition(db.Model):
    __tablename__ = 'propositions'
    id = Column(Integer, primary_key=True)
    title = Column(String(128), nullable=False)
    description = Column(String(1024))
    image = Column(String(512))
    points_required = Column(Integer, nullable=False, default=0)
    type = Column(String(32), nullable=False, default='code')
    content = Column(String(1024), nullable=False)


@app.route('/images', methods=['GET', 'POST'])
def upload_image():
    if request.method == 'GET':
        return send_from_directory(app.config['UPLOAD_FOLDER'], request.args['filename'])
    # POST
    image_file = request.files['image']
    name, ext = os.path.splitext(image_file.filename)
    file_name = str(uuid4()) + ext
    image_file.save(os.path.join(app.config['UPLOAD_FOLDER'], file_name))
    return jsonify(filename=file_name)


@app.route('/kids', methods=['POST'])
def add_kid():
    new_kid = Kid(**request.json)
    db.session.add(new_kid)
    db.session.commit()
    return '', 201


@app.route('/login', methods=['POST'])
def login():
    phone_number = request.json['phone_number']
    account_id = request.json['account_id']
    kid = Kid.query.filter_by(account_id=account_id).one_or_none()
    if kid is None:
        abort(400)
    if kid.phone_number is None:
        kid.phone_number = phone_number
        db.session.commit()
    token = create_access_token(identity=kid.id)
    return jsonify(token=token, register=(kid.goal is None))


@app.route('/tags', methods=['GET', 'POST'])
def manage_tags():
    if request.method == 'GET':
        tag_name_start = request.args.get('tag', '').lower()
        all_tags = Tag.query.all()
        tag_names = [tag.name for tag in all_tags if tag.name.lower().startswith(tag_name_start)]
        return jsonify(tags=tag_names)
    # POST
    tag_name = request.json['tag']
    new_tag = Tag(name=tag_name)
    try:
        db.session.add(new_tag)
        db.session.commit()
    except Exception:  # noqa
        return '', 400
    return '', 201


@app.route('/kids/interests', methods=['POST'])
@jwt_required
def add_interests():
    kid = Kid.query.get(get_jwt_identity())
    for tag_name in request.json['interests']:
        tag = Tag.query.filter_by(name=tag_name).one_or_none()
        if tag is not None:
            kid.interests.append(tag)
    db.session.commit()
    return '', 200


@app.route('/kids/goal', methods=['POST', 'PUT'])
@jwt_required
def set_goal():
    goal = request.json['goal']
    kid_id = get_jwt_identity()
    kid = Kid.query.get(kid_id)
    kid.goal = goal
    if request.method == 'POST':
        Task.query.filter_by(kid_id=kid.id).delete()
    db.session.commit()
    return '', 200


@app.route('/kids/avatar', methods=['POST'])
@jwt_required
def set_avatar():
    kid = Kid.query.get(get_jwt_identity())
    kid.avatar = request.json['avatar']
    db.session.commit()
    return '', 200


@app.route('/kids/goal/tasks', methods=['GET', 'POST', 'PUT'])
@jwt_required
def manage_tasks():
    kid = Kid.query.get(get_jwt_identity())
    if request.method == 'GET':
        tasks = [
            {'id': task.id, 'text': task.text, 'done': task.done} for task in sorted(kid.tasks, key=lambda t: t.order)
        ]
        return jsonify(tasks=tasks)
    if request.method == 'POST':
        new_task = Task(kid_id=kid.id, **request.json)
        db.session.add(new_task)
        db.session.commit()
        return '', 201
    # PUT
    task_id = request.json['id']
    done = request.json['done']
    task = Task.query.get(task_id)
    if task is None:
        abort(404)
    task.done = done
    db.session.commit()
    return '', 200


@app.route('/propositions', methods=['GET', 'POST'])
def manage_propositions():
    if request.method == 'GET':
        all_propositions = [
            {
                'id': propos.id,
                'title': propos.title,
                'image': propos.image,
                'points': propos.points_required,
            }
            for propos in Proposition.query.all()
        ]
        return jsonify(propositions=all_propositions)
    # POST
    new_propos = Proposition(**request.json)
    db.session.add(new_propos)
    db.session.commit()
    return '', 201


@app.route('/propositions/card')
@jwt_required
def get_proposition_card():
    kid = Kid.query.get(get_jwt_identity())
    propos = Proposition.query.get(request.json['id'])
    proposition = {
        'title': propos.title,
        'image': propos.image,
        'description': propos.description,
        'type': propos.type,
        'points': propos.points_required,
    }
    if kid.points >= propos.points_required:
        proposition['content'] = propos.content
    return jsonify(proposition=proposition)


@app.route('/kids/profile')
@jwt_required
def profile():
    kid = Kid.query.get(get_jwt_identity())
    kid_profile = {
        'account_id': kid.account_id,
        'goal': kid.goal,
        'tasks': [
            {'id': task.id, 'text': task.text, 'done': task.done} for task in sorted(kid.tasks, key=lambda t: t.order)
        ],
        'interests': [interest.name for interest in kid.interests],
        'name': kid.name,
        'points': kid.points,
        'avatar': kid.avatar,
        'mentorship': kid.mentorship.name,
    }
    return jsonify(profile=kid_profile)


@app.route('/kids/points/add', methods=['POST'])
def add_points():
    kid = Kid.query.filter_by(account_id=request.json['account_id']).one()
    kid.points += request.json['amount']
    if kid.points >= MENTORSHIP_REQUIRES and kid.mentorship == MentorshipState.not_enough_points:
        kid.mentorship = MentorshipState.uninitialized
    db.session.commit()
    return '', 200


@app.route('/mentors', methods=['GET', 'POST'])
def manage_mentors():
    if request.method == 'GET':
        mentors = [
            {
                'id': mentor.id,
                'name': mentor.name,
                'photo': mentor.photo,
                'position': mentor.position,
                'bio': mentor.bio,
                'expertises': [exp.name for exp in mentor.expertises]
            }
            for mentor in Mentor.query.all()
        ]
        return jsonify(mentors=mentors)
    # POST
    new_mentor = Mentor(**request.json)
    db.session.add(new_mentor)
    db.session.commit()
    return '', 201


@app.route('/mentors/expertises', methods=['POST'])
def add_expertises():
    mentor = Mentor.query.get(request.json['id'])
    for exp in request.json['expertises']:
        expertise = Tag.query.filter_by(name=exp).one_or_none()
        if expertise is not None:
            mentor.expertises.append(expertise)
    db.session.commit()
    return '', 200


@app.route('/kids/mentor/like', methods=['POST'])
@jwt_required
def like_mentor():
    kid = Kid.query.get(get_jwt_identity())
    mentor_id = request.json['id']
    mentor = Mentor.query.get(mentor_id)
    kid.likes.append(mentor)
    db.session.commit()
    return '', 200


@app.route('/kids/mentor/ready', methods=['POST'])
@jwt_required
def wait_for_mentor():
    kid = Kid.query.get(get_jwt_identity())
    kid.mentorship = MentorshipState.waiting
    db.session.commit()
    return '', 200
