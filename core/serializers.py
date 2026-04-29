from rest_framework import serializers
from .models import (
    ExamAttempt,
    ExamQuestion,
    ExamTemplate,
    Option,
    Question,
    StudentAnswer,
    Topic,
)

class OptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Option
        fields = ["id", "text", "is_correct"]
        extra_kwargs = {
            "is_correct": {"write_only": True}  # no exponer cual es la correcta
        }

class QuestionSerializer(serializers.ModelSerializer):
    options = OptionSerializer(many=True)
    topic_name = serializers.CharField(source="topic.name", read_only=True)
    image = serializers.ImageField(required=False, allow_null=True)


    class Meta:
        model = Question
        fields = [
            "id", "text", "topic", "topic_name", "difficulty",
            "reference_law", "reference_book", "explanation", "image", "options"
        ]

    def create(self, validated_data):
        options_data = validated_data.pop("options", [])
        q = Question.objects.create(**validated_data)
        for od in options_data:
            Option.objects.create(question=q, **od)
        return q

    def update(self, instance, validated_data):
        options_data = validated_data.pop("options", None)
        for attr, val in validated_data.items():
            setattr(instance, attr, val)
        instance.save()
        if options_data is not None:
            instance.options.all().delete()
            for od in options_data:
                Option.objects.create(question=instance, **od)
        return instance

class ExamQuestionSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(read_only=True)
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = ExamQuestion
        fields = [
            "id", "question_text", "options", "topic", "difficulty",
            "reference_law", "reference_book", "explanation", "image", "image_url"
        ]

    def get_image_url(self, obj):
        if not obj.image:
            return None
        request = self.context.get("request")
        url = obj.image.url
        if request is not None:
            return request.build_absolute_uri(url)
        return url

    def to_representation(self, instance):
        data = super().to_representation(instance)
        include_feedback = self.context.get("include_feedback", False)

        sanitized_options = []
        for option in data.get("options", []) or []:
            if isinstance(option, dict) and not include_feedback:
                option = {k: v for k, v in option.items() if k != "is_correct"}
            sanitized_options.append(option)
        data["options"] = sanitized_options

        if not include_feedback:
            data.pop("reference_law", None)
            data.pop("reference_book", None)
            data.pop("explanation", None)

        return data

class StudentAnswerSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentAnswer
        fields = ["id", "exam_question", "selected_index", "selected_indexes", "is_correct"]
        read_only_fields = ["is_correct"]

class ExamAttemptSerializer(serializers.ModelSerializer):
    exam_questions = ExamQuestionSerializer(many=True, read_only=True)

    class Meta:
        model = ExamAttempt
        fields = [
            "id", "template", "status", "started_at",
            "finished_at", "score", "exam_questions"
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        include_feedback = self.context.get("include_feedback", False)
        eq_context = {"include_feedback": include_feedback}
        request = self.context.get("request")
        if request is not None:
            eq_context["request"] = request
        data["exam_questions"] = ExamQuestionSerializer(
            instance.exam_questions.all(),
            many=True,
            context=eq_context,
        ).data
        return data


class StartExamSerializer(serializers.Serializer):
    template_id = serializers.PrimaryKeyRelatedField(
        source="template", queryset=ExamTemplate.objects.all()
    )


class AnswerExamSerializer(serializers.Serializer):
    exam_question_id = serializers.PrimaryKeyRelatedField(
        source="exam_question", queryset=ExamQuestion.objects.all()
    )
    selected_index = serializers.IntegerField(required=False)
    selected_indexes = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        allow_empty=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        attempt = self.context.get("attempt")
        if attempt is not None:
            self.fields["exam_question_id"].queryset = attempt.exam_questions.all()

    def validate_selected_index(self, value):
        if value < 0:
            raise serializers.ValidationError("selected_index no puede ser negativo.")
        return value

    def validate_selected_indexes(self, value):
        if not value:
            raise serializers.ValidationError(
                "Debes proporcionar al menos una opcion."
            )
        for item in value:
            if item < 0:
                raise serializers.ValidationError(
                    "selected_indexes no puede contener valores negativos."
                )
        return value

    def validate(self, attrs):
        selected_indexes = attrs.get("selected_indexes")
        single = attrs.pop("selected_index", None)
        if selected_indexes is None:
            if single is None:
                raise serializers.ValidationError(
                    {"selected_indexes": "Debes seleccionar al menos una opcion."}
                )
            selected_indexes = [single]
        else:
            if single is not None:
                selected_indexes.append(single)
        attrs["selected_indexes"] = selected_indexes
        return attrs

    def validate_exam_question(self, exam_question):
        attempt = self.context.get("attempt")
        if attempt is not None and exam_question.attempt_id != attempt.id:
            raise serializers.ValidationError(
                "La pregunta no pertenece a este intento."
            )
        return exam_question
