from django.test import TestCase
from .agent_runtime import keyword_search
from .models import User, Course, StoredFile, Material, KnowledgeEntry, KnowledgeChunk


class IndexedKeywordBoundaryTests(TestCase):
    def test_same_match_never_leaks_other_course_or_unready_source(self):
        user=User.objects.create_user('keyword-bounds@example.test')
        own=Course.objects.create(name='Visible',created_by=user)
        other=Course.objects.create(name='Other',created_by=user)
        expected=None
        for number,(course,entry_status,chunk_status) in enumerate([
                (own,'ready','ready'),(other,'ready','ready'),
                (own,'failed','ready'),(own,'pending','ready'),(own,'ready','pending')]):
            file=StoredFile.objects.create(course=course,uploaded_by=user,original_name=f'{number}.txt',
                kind='material',file=f'synthetic/{number}.txt',size=10)
            material=Material.objects.create(course=course,title=f'Synthetic {number}',attachment=file)
            entry=KnowledgeEntry.objects.create(material=material,status=entry_status)
            chunk=KnowledgeChunk.objects.create(entry=entry,chunk_index=0,chunk_text='benchmarkneedle',status=chunk_status)
            if number==0: expected=chunk.pk
        hits=keyword_search(own.pk,'benchmarkneedle')
        self.assertEqual([h['chunk_id'] for h in hits],[expected])
        self.assertTrue(all(h['chunk_id']==expected for h in keyword_search(own.pk,"benchmarkneedle' OR 1=1 --")))
        self.assertEqual(keyword_search(own.pk,'   '),[])
