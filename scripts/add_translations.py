#!/usr/bin/env python3
"""Add translations for new Phase 1 i18n strings across all languages."""

import re
import os

TRANSLATIONS = {
    # msgid: {lang_code: translation}
    "Your Profile": {
        "es": "Tu Perfil", "fr": "Votre Profil", "de": "Ihr Profil",
        "pt": "Seu Perfil", "zh": "您的个人资料", "ar": "ملفك الشخصي",
        "hi": "आपकी प्रोफ़ाइल", "ja": "プロフィール", "ko": "내 프로필", "nl": "Uw Profiel",
    },
    "Create Profile": {
        "es": "Crear Perfil", "fr": "Créer un Profil", "de": "Profil Erstellen",
        "pt": "Criar Perfil", "zh": "创建个人资料", "ar": "إنشاء ملف شخصي",
        "hi": "प्रोफ़ाइल बनाएं", "ja": "プロフィール作成", "ko": "프로필 생성", "nl": "Profiel Aanmaken",
    },
    "Notifications": {
        "es": "Notificaciones", "fr": "Notifications", "de": "Benachrichtigungen",
        "pt": "Notificações", "zh": "通知", "ar": "الإشعارات",
        "hi": "सूचनाएं", "ja": "通知", "ko": "알림", "nl": "Meldingen",
    },
    "My Briefings": {
        "es": "Mis Informes", "fr": "Mes Briefings", "de": "Meine Briefings",
        "pt": "Meus Briefings", "zh": "我的简报", "ar": "ملخصاتي",
        "hi": "मेरे ब्रीफिंग", "ja": "マイブリーフィング", "ko": "내 브리핑", "nl": "Mijn Briefings",
    },
    "Settings": {
        "es": "Configuración", "fr": "Paramètres", "de": "Einstellungen",
        "pt": "Configurações", "zh": "设置", "ar": "الإعدادات",
        "hi": "सेटिंग्स", "ja": "設定", "ko": "설정", "nl": "Instellingen",
    },
    "Partner Portal": {
        "es": "Portal de Socios", "fr": "Portail Partenaire", "de": "Partnerportal",
        "pt": "Portal de Parceiros", "zh": "合作伙伴门户", "ar": "بوابة الشركاء",
        "hi": "पार्टनर पोर्टल", "ja": "パートナーポータル", "ko": "파트너 포털", "nl": "Partnerportaal",
    },
    "Admin": {
        "es": "Administrador", "fr": "Administration", "de": "Administration",
        "pt": "Administrador", "zh": "管理员", "ar": "الإدارة",
        "hi": "व्यवस्थापक", "ja": "管理者", "ko": "관리자", "nl": "Beheerder",
    },
    "Sign out": {
        "es": "Cerrar sesión", "fr": "Se déconnecter", "de": "Abmelden",
        "pt": "Sair", "zh": "退出登录", "ar": "تسجيل الخروج",
        "hi": "साइन आउट", "ja": "サインアウト", "ko": "로그아웃", "nl": "Uitloggen",
    },
    "Sign in": {
        "es": "Iniciar sesión", "fr": "Se connecter", "de": "Anmelden",
        "pt": "Entrar", "zh": "登录", "ar": "تسجيل الدخول",
        "hi": "साइन इन", "ja": "サインイン", "ko": "로그인", "nl": "Inloggen",
    },
    "Get Started": {
        "es": "Empezar", "fr": "Commencer", "de": "Loslegen",
        "pt": "Começar", "zh": "开始使用", "ar": "ابدأ الآن",
        "hi": "शुरू करें", "ja": "はじめる", "ko": "시작하기", "nl": "Aan de Slag",
    },
    "Welcome back, %(name)s!": {
        "es": "¡Bienvenido de nuevo, %(name)s!", "fr": "Bon retour, %(name)s !",
        "de": "Willkommen zurück, %(name)s!", "pt": "Bem-vindo de volta, %(name)s!",
        "zh": "欢迎回来，%(name)s！", "ar": "مرحباً بعودتك، %(name)s!",
        "hi": "वापस स्वागत है, %(name)s!", "ja": "おかえりなさい、%(name)s！",
        "ko": "다시 오신 것을 환영합니다, %(name)s!", "nl": "Welkom terug, %(name)s!",
    },
    "Here's an overview of your programmes and discussions.": {
        "es": "Aquí tienes un resumen de tus programas y debates.",
        "fr": "Voici un aperçu de vos programmes et discussions.",
        "de": "Hier ist eine Übersicht Ihrer Programme und Diskussionen.",
        "pt": "Aqui está uma visão geral dos seus programas e discussões.",
        "zh": "这是您的项目和讨论概览。", "ar": "إليك نظرة عامة على برامجك ومناقشاتك.",
        "hi": "यहां आपके कार्यक्रमों और चर्चाओं का अवलोकन है।",
        "ja": "プログラムとディスカッションの概要です。",
        "ko": "프로그램과 토론의 개요입니다.", "nl": "Hier is een overzicht van uw programma's en discussies.",
    },
    "Dashboard": {
        "es": "Panel de control", "fr": "Tableau de bord", "de": "Dashboard",
        "pt": "Painel", "zh": "仪表板", "ar": "لوحة التحكم",
        "hi": "डैशबोर्ड", "ja": "ダッシュボード", "ko": "대시보드", "nl": "Dashboard",
    },
    "Discussion Views": {
        "es": "Vistas de Debates", "fr": "Vues des Discussions", "de": "Diskussionsaufrufe",
        "pt": "Visualizações de Discussões", "zh": "讨论浏览量", "ar": "مشاهدات النقاشات",
        "hi": "चर्चा दृश्य", "ja": "ディスカッション閲覧数", "ko": "토론 조회수", "nl": "Discussie Weergaven",
    },
    "Profile Views": {
        "es": "Vistas de Perfil", "fr": "Vues du Profil", "de": "Profilaufrufe",
        "pt": "Visualizações de Perfil", "zh": "个人资料浏览量", "ar": "مشاهدات الملف الشخصي",
        "hi": "प्रोफ़ाइल दृश्य", "ja": "プロフィール閲覧数", "ko": "프로필 조회수", "nl": "Profiel Weergaven",
    },
    "Profile photo": {
        "es": "Foto de perfil", "fr": "Photo de profil", "de": "Profilfoto",
        "pt": "Foto de perfil", "zh": "个人照片", "ar": "صورة الملف الشخصي",
        "hi": "प्रोफ़ाइल फोटो", "ja": "プロフィール写真", "ko": "프로필 사진", "nl": "Profielfoto",
    },
    "Individual": {
        "es": "Individual", "fr": "Individuel", "de": "Einzelperson",
        "pt": "Individual", "zh": "个人", "ar": "فردي",
        "hi": "व्यक्तिगत", "ja": "個人", "ko": "개인", "nl": "Individu",
    },
    "Company logo": {
        "es": "Logo de empresa", "fr": "Logo de l'entreprise", "de": "Firmenlogo",
        "pt": "Logo da empresa", "zh": "公司标志", "ar": "شعار الشركة",
        "hi": "कंपनी लोगो", "ja": "会社ロゴ", "ko": "회사 로고", "nl": "Bedrijfslogo",
    },
    "Organisation": {
        "es": "Organización", "fr": "Organisation", "de": "Organisation",
        "pt": "Organização", "zh": "组织", "ar": "مؤسسة",
        "hi": "संगठन", "ja": "組織", "ko": "조직", "nl": "Organisatie",
    },
    "View": {
        "es": "Ver", "fr": "Voir", "de": "Ansehen",
        "pt": "Ver", "zh": "查看", "ar": "عرض",
        "hi": "देखें", "ja": "表示", "ko": "보기", "nl": "Bekijken",
    },
    "Edit": {
        "es": "Editar", "fr": "Modifier", "de": "Bearbeiten",
        "pt": "Editar", "zh": "编辑", "ar": "تعديل",
        "hi": "संपादित करें", "ja": "編集", "ko": "편집", "nl": "Bewerken",
    },
    "Set up your profile so others can find you.": {
        "es": "Configura tu perfil para que otros puedan encontrarte.",
        "fr": "Configurez votre profil pour que les autres puissent vous trouver.",
        "de": "Richten Sie Ihr Profil ein, damit andere Sie finden können.",
        "pt": "Configure seu perfil para que outros possam encontrá-lo.",
        "zh": "设置您的个人资料，以便其他人可以找到您。",
        "ar": "أنشئ ملفك الشخصي حتى يتمكن الآخرون من العثور عليك.",
        "hi": "अपनी प्रोफ़ाइल सेट करें ताकि दूसरे आपको ढूंढ सकें।",
        "ja": "他のユーザーが見つけられるようにプロフィールを設定してください。",
        "ko": "다른 사람들이 찾을 수 있도록 프로필을 설정하세요.", "nl": "Stel uw profiel in zodat anderen u kunnen vinden.",
    },
    "Create profile": {
        "es": "Crear perfil", "fr": "Créer un profil", "de": "Profil erstellen",
        "pt": "Criar perfil", "zh": "创建个人资料", "ar": "إنشاء ملف شخصي",
        "hi": "प्रोफ़ाइल बनाएं", "ja": "プロフィールを作成", "ko": "프로필 만들기", "nl": "Profiel aanmaken",
    },
    "Create": {
        "es": "Crear", "fr": "Créer", "de": "Erstellen",
        "pt": "Criar", "zh": "创建", "ar": "إنشاء",
        "hi": "बनाएं", "ja": "作成", "ko": "만들기", "nl": "Aanmaken",
    },
    "New Programme": {
        "es": "Nuevo Programa", "fr": "Nouveau Programme", "de": "Neues Programm",
        "pt": "Novo Programa", "zh": "新项目", "ar": "برنامج جديد",
        "hi": "नया कार्यक्रम", "ja": "新しいプログラム", "ko": "새 프로그램", "nl": "Nieuw Programma",
    },
    "Group discussions into a campaign": {
        "es": "Agrupa debates en una campaña", "fr": "Regroupez les discussions en une campagne",
        "de": "Diskussionen zu einer Kampagne gruppieren", "pt": "Agrupe discussões em uma campanha",
        "zh": "将讨论归入一个活动", "ar": "اجمع النقاشات في حملة",
        "hi": "चर्चाओं को एक अभियान में समूहित करें", "ja": "ディスカッションをキャンペーンにまとめる",
        "ko": "토론을 캠페인으로 그룹화", "nl": "Groepeer discussies in een campagne",
    },
    "New Discussion": {
        "es": "Nuevo Debate", "fr": "Nouvelle Discussion", "de": "Neue Diskussion",
        "pt": "Nova Discussão", "zh": "新讨论", "ar": "نقاش جديد",
        "hi": "नई चर्चा", "ja": "新しいディスカッション", "ko": "새 토론", "nl": "Nieuwe Discussie",
    },
    "Start a discussion on any topic": {
        "es": "Inicia un debate sobre cualquier tema", "fr": "Lancez une discussion sur n'importe quel sujet",
        "de": "Starten Sie eine Diskussion zu jedem Thema", "pt": "Inicie uma discussão sobre qualquer tópico",
        "zh": "就任何话题开始讨论", "ar": "ابدأ نقاشاً حول أي موضوع",
        "hi": "किसी भी विषय पर चर्चा शुरू करें", "ja": "任意のトピックについてディスカッションを始める",
        "ko": "어떤 주제든 토론 시작", "nl": "Start een discussie over elk onderwerp",
    },
    "Workspace": {
        "es": "Espacio de trabajo", "fr": "Espace de travail", "de": "Arbeitsbereich",
        "pt": "Espaço de trabalho", "zh": "工作区", "ar": "مساحة العمل",
        "hi": "कार्यक्षेत्र", "ja": "ワークスペース", "ko": "작업공간", "nl": "Werkruimte",
    },
    "Public profile": {
        "es": "Perfil público", "fr": "Profil public", "de": "Öffentliches Profil",
        "pt": "Perfil público", "zh": "公开个人资料", "ar": "الملف الشخصي العام",
        "hi": "सार्वजनिक प्रोफ़ाइल", "ja": "公開プロフィール", "ko": "공개 프로필", "nl": "Openbaar Profiel",
    },
    "Continue Where You Left Off": {
        "es": "Continúa Donde Lo Dejaste", "fr": "Continuez Où Vous Étiez",
        "de": "Dort Weitermachen, Wo Sie Aufgehört Haben", "pt": "Continue de Onde Parou",
        "zh": "继续您离开的地方", "ar": "تابع من حيث توقفت",
        "hi": "जहां छोड़ा था वहां से जारी रखें", "ja": "途中から続ける",
        "ko": "중단한 곳에서 계속하기", "nl": "Ga Verder Waar U Gebleven Was",
    },
    "Continue": {
        "es": "Continuar", "fr": "Continuer", "de": "Weiter",
        "pt": "Continuar", "zh": "继续", "ar": "متابعة",
        "hi": "जारी रखें", "ja": "続ける", "ko": "계속하기", "nl": "Doorgaan",
    },
    "My Programmes": {
        "es": "Mis Programas", "fr": "Mes Programmes", "de": "Meine Programme",
        "pt": "Meus Programas", "zh": "我的项目", "ar": "برامجي",
        "hi": "मेरे कार्यक्रम", "ja": "マイプログラム", "ko": "내 프로그램", "nl": "Mijn Programma's",
    },
    "Programmes you own, steward, or participate in": {
        "es": "Programas que posees, administras o en los que participas",
        "fr": "Programmes que vous possédez, gérez ou auxquels vous participez",
        "de": "Programme, die Sie besitzen, verwalten oder an denen Sie teilnehmen",
        "pt": "Programas que você possui, administra ou participa",
        "zh": "您拥有、管理或参与的项目", "ar": "البرامج التي تمتلكها أو تديرها أو تشارك فيها",
        "hi": "वे कार्यक्रम जिनके आप मालिक हैं, प्रबंधित करते हैं, या भाग लेते हैं",
        "ja": "所有、管理、または参加しているプログラム",
        "ko": "소유하거나 관리하거나 참여하는 프로그램", "nl": "Programma's die u bezit, beheert of waaraan u deelneemt",
    },
    "New": {
        "es": "Nuevo", "fr": "Nouveau", "de": "Neu",
        "pt": "Novo", "zh": "新建", "ar": "جديد",
        "hi": "नया", "ja": "新規", "ko": "새로 만들기", "nl": "Nieuw",
    },
    "Showing 6 of %(count)s —": {
        "es": "Mostrando 6 de %(count)s —", "fr": "Affichage de 6 sur %(count)s —",
        "de": "Zeige 6 von %(count)s —", "pt": "Mostrando 6 de %(count)s —",
        "zh": "显示 %(count)s 中的 6 个 —", "ar": "عرض 6 من %(count)s —",
        "hi": "%(count)s में से 6 दिखाए जा रहे हैं —", "ja": "%(count)s 件中 6 件を表示 —",
        "ko": "%(count)s 개 중 6개 표시 —", "nl": "6 van %(count)s weergeven —",
    },
    "view all in workspace": {
        "es": "ver todos en el espacio de trabajo", "fr": "tout voir dans l'espace de travail",
        "de": "alle im Arbeitsbereich anzeigen", "pt": "ver todos no espaço de trabalho",
        "zh": "在工作区中查看全部", "ar": "عرض الكل في مساحة العمل",
        "hi": "कार्यक्षेत्र में सभी देखें", "ja": "ワークスペースで全件表示",
        "ko": "작업공간에서 모두 보기", "nl": "alles bekijken in werkruimte",
    },
    "No programmes yet": {
        "es": "Aún no hay programas", "fr": "Aucun programme pour l'instant",
        "de": "Noch keine Programme", "pt": "Nenhum programa ainda",
        "zh": "暂无项目", "ar": "لا توجد برامج بعد",
        "hi": "अभी तक कोई कार्यक्रम नहीं", "ja": "まだプログラムはありません",
        "ko": "아직 프로그램이 없습니다", "nl": "Nog geen programma's",
    },
    "Programmes group discussions into structured engagement campaigns.": {
        "es": "Los programas agrupan debates en campañas de participación estructuradas.",
        "fr": "Les programmes regroupent les discussions en campagnes d'engagement structurées.",
        "de": "Programme gruppieren Diskussionen in strukturierte Engagement-Kampagnen.",
        "pt": "Os programas agrupam discussões em campanhas de engajamento estruturadas.",
        "zh": "项目将讨论归入结构化的参与活动。",
        "ar": "تجمع البرامج النقاشات في حملات مشاركة منظمة.",
        "hi": "कार्यक्रम चर्चाओं को संरचित भागीदारी अभियानों में समूहित करते हैं।",
        "ja": "プログラムはディスカッションを構造化されたエンゲージメントキャンペーンにまとめます。",
        "ko": "프로그램은 토론을 구조화된 참여 캠페인으로 그룹화합니다.",
        "nl": "Programma's groeperen discussies in gestructureerde betrokkenheidscampagnes.",
    },
    "Create your first programme": {
        "es": "Crea tu primer programa", "fr": "Créez votre premier programme",
        "de": "Erstellen Sie Ihr erstes Programm", "pt": "Crie seu primeiro programa",
        "zh": "创建您的第一个项目", "ar": "أنشئ برنامجك الأول",
        "hi": "अपना पहला कार्यक्रम बनाएं", "ja": "最初のプログラムを作成する",
        "ko": "첫 번째 프로그램 만들기", "nl": "Maak uw eerste programma",
    },
    "Recent Updates": {
        "es": "Actualizaciones Recientes", "fr": "Mises à Jour Récentes", "de": "Aktuelle Updates",
        "pt": "Atualizações Recentes", "zh": "最新动态", "ar": "التحديثات الأخيرة",
        "hi": "हाल के अपडेट", "ja": "最近の更新", "ko": "최근 업데이트", "nl": "Recente Updates",
    },
    "Discussion activity and alerts": {
        "es": "Actividad de debates y alertas", "fr": "Activité des discussions et alertes",
        "de": "Diskussionsaktivität und Benachrichtigungen", "pt": "Atividade de discussões e alertas",
        "zh": "讨论活动和提醒", "ar": "نشاط النقاشات والتنبيهات",
        "hi": "चर्चा गतिविधि और अलर्ट", "ja": "ディスカッションのアクティビティとアラート",
        "ko": "토론 활동 및 알림", "nl": "Discussie-activiteit en meldingen",
    },
    "You have no notifications yet.": {
        "es": "Aún no tienes notificaciones.", "fr": "Vous n'avez pas encore de notifications.",
        "de": "Sie haben noch keine Benachrichtigungen.", "pt": "Você ainda não tem notificações.",
        "zh": "您还没有通知。", "ar": "ليس لديك إشعارات بعد.",
        "hi": "आपके पास अभी तक कोई सूचना नहीं है।", "ja": "まだ通知はありません。",
        "ko": "아직 알림이 없습니다.", "nl": "U heeft nog geen meldingen.",
    },
    "Participating": {
        "es": "Participando", "fr": "Participation", "de": "Teilnehmend",
        "pt": "Participando", "zh": "正在参与", "ar": "المشاركة",
        "hi": "भाग लेना", "ja": "参加中", "ko": "참여 중", "nl": "Deelnemend",
    },
    "Discussions you have joined or contributed to": {
        "es": "Debates en los que te has unido o contribuido",
        "fr": "Discussions auxquelles vous avez participé ou contribué",
        "de": "Diskussionen, denen Sie beigetreten sind oder zu denen Sie beigetragen haben",
        "pt": "Discussões às quais você se juntou ou contribuiu",
        "zh": "您加入或贡献过的讨论", "ar": "النقاشات التي انضممت إليها أو ساهمت فيها",
        "hi": "वे चर्चाएं जिनमें आपने भाग लिया या योगदान दिया",
        "ja": "参加または貢献したディスカッション",
        "ko": "참여하거나 기여한 토론", "nl": "Discussies waaraan u heeft deelgenomen of bijgedragen",
    },
    "View activity": {
        "es": "Ver actividad", "fr": "Voir l'activité", "de": "Aktivität anzeigen",
        "pt": "Ver atividade", "zh": "查看活动", "ar": "عرض النشاط",
        "hi": "गतिविधि देखें", "ja": "アクティビティを表示", "ko": "활동 보기", "nl": "Activiteit bekijken",
    },
    "Voted": {
        "es": "Votado", "fr": "Voté", "de": "Abgestimmt",
        "pt": "Votado", "zh": "已投票", "ar": "صوّت",
        "hi": "वोट दिया", "ja": "投票済み", "ko": "투표함", "nl": "Gestemd",
    },
    "Statement": {
        "es": "Declaración", "fr": "Déclaration", "de": "Aussage",
        "pt": "Declaração", "zh": "声明", "ar": "بيان",
        "hi": "वक्तव्य", "ja": "ステートメント", "ko": "진술", "nl": "Verklaring",
    },
    "Response": {
        "es": "Respuesta", "fr": "Réponse", "de": "Antwort",
        "pt": "Resposta", "zh": "回复", "ar": "رد",
        "hi": "प्रतिक्रिया", "ja": "返答", "ko": "답변", "nl": "Reactie",
    },
    "Vote on statements or add an argument to build your activity history.": {
        "es": "Vota en declaraciones o añade un argumento para construir tu historial de actividad.",
        "fr": "Votez sur des déclarations ou ajoutez un argument pour construire votre historique d'activité.",
        "de": "Stimmen Sie über Aussagen ab oder fügen Sie ein Argument hinzu, um Ihre Aktivitätshistorie aufzubauen.",
        "pt": "Vote em declarações ou adicione um argumento para construir seu histórico de atividades.",
        "zh": "对声明投票或添加论点以建立您的活动历史。",
        "ar": "صوّت على البيانات أو أضف حجة لبناء سجل نشاطك.",
        "hi": "वक्तव्यों पर वोट करें या अपनी गतिविधि इतिहास बनाने के लिए एक तर्क जोड़ें।",
        "ja": "ステートメントに投票するか、議論を追加してアクティビティ履歴を構築してください。",
        "ko": "진술에 투표하거나 주장을 추가하여 활동 기록을 쌓으세요.",
        "nl": "Stem op verklaringen of voeg een argument toe om uw activiteitsgeschiedenis op te bouwen.",
    },
    "Saved Discussions": {
        "es": "Debates Guardados", "fr": "Discussions Sauvegardées", "de": "Gespeicherte Diskussionen",
        "pt": "Discussões Salvas", "zh": "已保存的讨论", "ar": "النقاشات المحفوظة",
        "hi": "सहेजी गई चर्चाएं", "ja": "保存済みディスカッション", "ko": "저장된 토론", "nl": "Opgeslagen Discussies",
    },
    "Keep track of discussions you want to revisit": {
        "es": "Lleva un registro de los debates que quieres volver a visitar",
        "fr": "Gardez une trace des discussions que vous souhaitez revisiter",
        "de": "Behalten Sie den Überblick über Diskussionen, die Sie erneut besuchen möchten",
        "pt": "Acompanhe as discussões que você deseja revisitar",
        "zh": "跟踪您想要重新访问的讨论", "ar": "تتبع النقاشات التي تريد العودة إليها",
        "hi": "उन चर्चाओं का ट्रैक रखें जिन्हें आप फिर से देखना चाहते हैं",
        "ja": "後で見返したいディスカッションを追跡する",
        "ko": "다시 방문하고 싶은 토론을 추적하세요", "nl": "Houd discussies bij die u opnieuw wilt bezoeken",
    },
    "View saved": {
        "es": "Ver guardados", "fr": "Voir les sauvegardés", "de": "Gespeicherte anzeigen",
        "pt": "Ver salvos", "zh": "查看已保存", "ar": "عرض المحفوظات",
        "hi": "सहेजे गए देखें", "ja": "保存済みを表示", "ko": "저장된 것 보기", "nl": "Opgeslagen bekijken",
    },
    "Save discussions from any discussion page to build your watchlist.": {
        "es": "Guarda debates desde cualquier página de debate para construir tu lista de seguimiento.",
        "fr": "Sauvegardez des discussions depuis n'importe quelle page de discussion pour construire votre liste de surveillance.",
        "de": "Speichern Sie Diskussionen von jeder Diskussionsseite, um Ihre Beobachtungsliste aufzubauen.",
        "pt": "Salve discussões de qualquer página de discussão para construir sua lista de acompanhamento.",
        "zh": "从任何讨论页面保存讨论以建立您的关注列表。",
        "ar": "احفظ النقاشات من أي صفحة نقاش لبناء قائمة المراقبة الخاصة بك.",
        "hi": "अपनी वॉचलिस्ट बनाने के लिए किसी भी चर्चा पृष्ठ से चर्चाएं सहेजें।",
        "ja": "どのディスカッションページからでもディスカッションを保存してウォッチリストを作成してください。",
        "ko": "모든 토론 페이지에서 토론을 저장하여 감시 목록을 만드세요.",
        "nl": "Sla discussies op van elke discussiepagina om uw volglijst op te bouwen.",
    },
    "Stay informed": {
        "es": "Mantente informado", "fr": "Restez informé", "de": "Bleiben Sie informiert",
        "pt": "Fique informado", "zh": "保持关注", "ar": "ابق على اطلاع",
        "hi": "सूचित रहें", "ja": "最新情報を入手", "ko": "최신 정보 받기", "nl": "Blijf op de hoogte",
    },
    "Subscribe using your account email —": {
        "es": "Suscríbete con el correo de tu cuenta —",
        "fr": "Abonnez-vous avec l'e-mail de votre compte —",
        "de": "Abonnieren Sie mit Ihrer Konto-E-Mail —",
        "pt": "Assine com o e-mail da sua conta —",
        "zh": "使用您的账户邮箱订阅 —", "ar": "اشترك باستخدام بريد حسابك —",
        "hi": "अपने खाते के ईमेल से सदस्यता लें —", "ja": "アカウントのメールで登録 —",
        "ko": "계정 이메일로 구독 —", "nl": "Abonneer met uw account-e-mail —",
    },
    "Daily Brief": {
        "es": "Resumen Diario", "fr": "Briefing Quotidien", "de": "Täglicher Brief",
        "pt": "Resumo Diário", "zh": "每日简报", "ar": "الملخص اليومي",
        "hi": "दैनिक संक्षिप्त", "ja": "デイリーブリーフ", "ko": "일일 브리핑", "nl": "Dagelijkse Brief",
    },
    "A curated news briefing delivered to your inbox": {
        "es": "Un resumen de noticias curado entregado a tu bandeja de entrada",
        "fr": "Un briefing d'actualités curé livré dans votre boîte de réception",
        "de": "Ein kuratiertes Nachrichten-Briefing in Ihrem Posteingang",
        "pt": "Um briefing de notícias curado entregue na sua caixa de entrada",
        "zh": "精选新闻简报直接发送到您的收件箱", "ar": "ملخص أخبار منتقى يصل إلى صندوق بريدك",
        "hi": "आपके इनबॉक्स में क्यूरेटेड समाचार संक्षिप्त",
        "ja": "厳選されたニュースブリーフィングをメールでお届け",
        "ko": "엄선된 뉴스 브리핑을 받은편지함으로", "nl": "Een samengestelde nieuwsbrief in uw inbox",
    },
    "Active": {
        "es": "Activo", "fr": "Actif", "de": "Aktiv",
        "pt": "Ativo", "zh": "已激活", "ar": "نشط",
        "hi": "सक्रिय", "ja": "アクティブ", "ko": "활성", "nl": "Actief",
    },
    "Manage preferences": {
        "es": "Gestionar preferencias", "fr": "Gérer les préférences", "de": "Einstellungen verwalten",
        "pt": "Gerenciar preferências", "zh": "管理偏好", "ar": "إدارة التفضيلات",
        "hi": "प्राथमिकताएं प्रबंधित करें", "ja": "設定を管理", "ko": "기본 설정 관리", "nl": "Voorkeuren beheren",
    },
    "Frequency": {
        "es": "Frecuencia", "fr": "Fréquence", "de": "Häufigkeit",
        "pt": "Frequência", "zh": "频率", "ar": "التكرار",
        "hi": "आवृत्ति", "ja": "頻度", "ko": "빈도", "nl": "Frequentie",
    },
    "Daily": {
        "es": "Diariamente", "fr": "Quotidien", "de": "Täglich",
        "pt": "Diariamente", "zh": "每天", "ar": "يومياً",
        "hi": "दैनिक", "ja": "毎日", "ko": "매일", "nl": "Dagelijks",
    },
    "Weekly": {
        "es": "Semanalmente", "fr": "Hebdomadaire", "de": "Wöchentlich",
        "pt": "Semanalmente", "zh": "每周", "ar": "أسبوعياً",
        "hi": "साप्ताहिक", "ja": "毎週", "ko": "매주", "nl": "Wekelijks",
    },
    "Send time": {
        "es": "Hora de envío", "fr": "Heure d'envoi", "de": "Versandzeit",
        "pt": "Hora de envio", "zh": "发送时间", "ar": "وقت الإرسال",
        "hi": "भेजने का समय", "ja": "送信時刻", "ko": "발송 시간", "nl": "Verzendtijd",
    },
    "Timezone": {
        "es": "Zona horaria", "fr": "Fuseau horaire", "de": "Zeitzone",
        "pt": "Fuso horário", "zh": "时区", "ar": "المنطقة الزمنية",
        "hi": "समय क्षेत्र", "ja": "タイムゾーン", "ko": "시간대", "nl": "Tijdzone",
    },
    "Subscribe to Daily Brief": {
        "es": "Suscribirse al Resumen Diario", "fr": "S'abonner au Briefing Quotidien",
        "de": "Täglichen Brief abonnieren", "pt": "Assinar o Resumo Diário",
        "zh": "订阅每日简报", "ar": "الاشتراك في الملخص اليومي",
        "hi": "दैनिक संक्षिप्त की सदस्यता लें", "ja": "デイリーブリーフを購読",
        "ko": "일일 브리핑 구독", "nl": "Abonneer op Dagelijkse Brief",
    },
    "Daily Question": {
        "es": "Pregunta Diaria", "fr": "Question Quotidienne", "de": "Tägliche Frage",
        "pt": "Pergunta Diária", "zh": "每日问题", "ar": "السؤال اليومي",
        "hi": "दैनिक प्रश्न", "ja": "デイリークエスチョン", "ko": "일일 질문", "nl": "Dagelijkse Vraag",
    },
    "A civic question in your inbox — vote in one click": {
        "es": "Una pregunta cívica en tu bandeja de entrada — vota con un clic",
        "fr": "Une question civique dans votre boîte de réception — votez en un clic",
        "de": "Eine Bürgerfrage in Ihrem Posteingang — mit einem Klick abstimmen",
        "pt": "Uma pergunta cívica na sua caixa de entrada — vote com um clique",
        "zh": "收件箱中的公民问题 — 一键投票", "ar": "سؤال مدني في صندوق بريدك — صوّت بنقرة واحدة",
        "hi": "आपके इनबॉक्स में एक नागरिक प्रश्न — एक क्लिक में वोट करें",
        "ja": "メールで届く市民の質問 — ワンクリックで投票",
        "ko": "받은편지함의 시민 질문 — 한 번의 클릭으로 투표", "nl": "Een burgervraag in uw inbox — stem met één klik",
    },
    "Weekly digest": {
        "es": "Resumen semanal", "fr": "Digest hebdomadaire", "de": "Wöchentlicher Digest",
        "pt": "Resumo semanal", "zh": "每周摘要", "ar": "الملخص الأسبوعي",
        "hi": "साप्ताहिक डाइजेस्ट", "ja": "週次ダイジェスト", "ko": "주간 요약", "nl": "Wekelijkse samenvatting",
    },
    "Monthly": {
        "es": "Mensualmente", "fr": "Mensuel", "de": "Monatlich",
        "pt": "Mensalmente", "zh": "每月", "ar": "شهرياً",
        "hi": "मासिक", "ja": "毎月", "ko": "매월", "nl": "Maandelijks",
    },
    "Time zone": {
        "es": "Zona horaria", "fr": "Fuseau horaire", "de": "Zeitzone",
        "pt": "Fuso horário", "zh": "时区", "ar": "المنطقة الزمنية",
        "hi": "समय क्षेत्र", "ja": "タイムゾーン", "ko": "시간대", "nl": "Tijdzone",
    },
    "Digest day": {
        "es": "Día del resumen", "fr": "Jour du digest", "de": "Digest-Tag",
        "pt": "Dia do resumo", "zh": "摘要日", "ar": "يوم الملخص",
        "hi": "डाइजेस्ट दिन", "ja": "ダイジェスト曜日", "ko": "요약 발송일", "nl": "Dag van het digest",
    },
    "Time": {
        "es": "Hora", "fr": "Heure", "de": "Zeit",
        "pt": "Hora", "zh": "时间", "ar": "الوقت",
        "hi": "समय", "ja": "時刻", "ko": "시간", "nl": "Tijd",
    },
    "Subscribe to Daily Question": {
        "es": "Suscribirse a la Pregunta Diaria", "fr": "S'abonner à la Question Quotidienne",
        "de": "Tägliche Frage abonnieren", "pt": "Assinar a Pergunta Diária",
        "zh": "订阅每日问题", "ar": "الاشتراك في السؤال اليومي",
        "hi": "दैनिक प्रश्न की सदस्यता लें", "ja": "デイリークエスチョンを購読",
        "ko": "일일 질문 구독", "nl": "Abonneer op Dagelijkse Vraag",
    },
    "Paid Briefings": {
        "es": "Informes de Pago", "fr": "Briefings Payants", "de": "Kostenpflichtige Briefings",
        "pt": "Briefings Pagos", "zh": "付费简报", "ar": "الملخصات المدفوعة",
        "hi": "सशुल्क ब्रीफिंग", "ja": "有料ブリーフィング", "ko": "유료 브리핑", "nl": "Betaalde Briefings",
    },
    "Your personalised AI-curated briefings": {
        "es": "Tus informes personalizados curados por IA",
        "fr": "Vos briefings personnalisés curatés par IA",
        "de": "Ihre personalisierten KI-kuratierten Briefings",
        "pt": "Seus briefings personalizados curados por IA",
        "zh": "您的个性化AI精选简报", "ar": "ملخصاتك الشخصية المنتقاة بواسطة الذكاء الاصطناعي",
        "hi": "आपके व्यक्तिगत AI-क्यूरेटेड ब्रीफिंग",
        "ja": "あなたのパーソナライズされたAIキュレーテッドブリーフィング",
        "ko": "맞춤형 AI 큐레이션 브리핑", "nl": "Uw gepersonaliseerde AI-samengestelde briefings",
    },
    "Go to my Briefings": {
        "es": "Ir a mis Informes", "fr": "Aller à mes Briefings", "de": "Zu meinen Briefings",
        "pt": "Ir para meus Briefings", "zh": "前往我的简报", "ar": "الانتقال إلى ملخصاتي",
        "hi": "मेरे ब्रीफिंग पर जाएं", "ja": "マイブリーフィングへ", "ko": "내 브리핑으로 이동", "nl": "Naar mijn Briefings",
    },
    "Manage Billing": {
        "es": "Gestionar Facturación", "fr": "Gérer la Facturation", "de": "Abrechnung verwalten",
        "pt": "Gerenciar Cobrança", "zh": "管理账单", "ar": "إدارة الفوترة",
        "hi": "बिलिंग प्रबंधित करें", "ja": "請求を管理", "ko": "결제 관리", "nl": "Facturering beheren",
    },
    "Get personalised AI-curated briefings delivered to your inbox. Set your topics, sources, and schedule.": {
        "es": "Recibe informes personalizados curados por IA en tu bandeja de entrada. Establece tus temas, fuentes y horario.",
        "fr": "Recevez des briefings personnalisés curatés par IA dans votre boîte de réception. Définissez vos sujets, sources et calendrier.",
        "de": "Erhalten Sie personalisierte, KI-kuratierte Briefings in Ihrem Posteingang. Legen Sie Ihre Themen, Quellen und Ihren Zeitplan fest.",
        "pt": "Receba briefings personalizados curados por IA na sua caixa de entrada. Defina seus tópicos, fontes e agenda.",
        "zh": "将个性化的AI精选简报发送到您的收件箱。设置您的主题、来源和时间表。",
        "ar": "احصل على ملخصات شخصية منتقاة بواسطة الذكاء الاصطناعي في بريدك. حدد موضوعاتك ومصادرك وجدولك الزمني.",
        "hi": "अपने इनबॉक्स में व्यक्तिगत AI-क्यूरेटेड ब्रीफिंग प्राप्त करें। अपने विषय, स्रोत और शेड्यूल सेट करें।",
        "ja": "パーソナライズされたAIキュレーテッドブリーフィングをメールでお届けします。トピック、ソース、スケジュールを設定してください。",
        "ko": "맞춤형 AI 큐레이션 브리핑을 받은편지함으로 받으세요. 주제, 출처, 일정을 설정하세요.",
        "nl": "Ontvang gepersonaliseerde AI-samengestelde briefings in uw inbox. Stel uw onderwerpen, bronnen en schema in.",
    },
    "Start a free trial": {
        "es": "Comenzar prueba gratuita", "fr": "Commencer un essai gratuit", "de": "Kostenlose Testversion starten",
        "pt": "Iniciar teste gratuito", "zh": "开始免费试用", "ar": "ابدأ تجربة مجانية",
        "hi": "मुफ्त ट्रायल शुरू करें", "ja": "無料トライアルを開始", "ko": "무료 체험 시작", "nl": "Gratis proefperiode starten",
    },
    "Your Discussions": {
        "es": "Tus Debates", "fr": "Vos Discussions", "de": "Ihre Diskussionen",
        "pt": "Suas Discussões", "zh": "您的讨论", "ar": "نقاشاتك",
        "hi": "आपकी चर्चाएं", "ja": "あなたのディスカッション", "ko": "내 토론", "nl": "Uw Discussies",
    },
    "Discussions you have created": {
        "es": "Debates que has creado", "fr": "Discussions que vous avez créées",
        "de": "Diskussionen, die Sie erstellt haben", "pt": "Discussões que você criou",
        "zh": "您创建的讨论", "ar": "النقاشات التي أنشأتها",
        "hi": "वे चर्चाएं जो आपने बनाई हैं", "ja": "作成したディスカッション",
        "ko": "내가 만든 토론", "nl": "Discussies die u heeft aangemaakt",
    },
    "No discussions yet": {
        "es": "Aún no hay debates", "fr": "Aucune discussion pour l'instant",
        "de": "Noch keine Diskussionen", "pt": "Nenhuma discussão ainda",
        "zh": "暂无讨论", "ar": "لا توجد نقاشات بعد",
        "hi": "अभी तक कोई चर्चा नहीं", "ja": "まだディスカッションはありません",
        "ko": "아직 토론이 없습니다", "nl": "Nog geen discussies",
    },
    "Start a discussion to gather opinions and build consensus.": {
        "es": "Inicia un debate para reunir opiniones y construir consenso.",
        "fr": "Lancez une discussion pour recueillir des opinions et construire un consensus.",
        "de": "Starten Sie eine Diskussion, um Meinungen zu sammeln und einen Konsens aufzubauen.",
        "pt": "Inicie uma discussão para coletar opiniões e construir consenso.",
        "zh": "开始一个讨论以收集意见并建立共识。", "ar": "ابدأ نقاشاً لجمع الآراء وبناء الإجماع.",
        "hi": "राय इकट्ठा करने और सहमति बनाने के लिए एक चर्चा शुरू करें।",
        "ja": "意見を集めてコンセンサスを構築するためにディスカッションを始めてください。",
        "ko": "의견을 모으고 합의를 형성하기 위해 토론을 시작하세요.",
        "nl": "Start een discussie om meningen te verzamelen en consensus te bereiken.",
    },
    "Start your first discussion": {
        "es": "Inicia tu primer debate", "fr": "Lancez votre première discussion",
        "de": "Starten Sie Ihre erste Diskussion", "pt": "Inicie sua primeira discussão",
        "zh": "开始您的第一个讨论", "ar": "ابدأ أول نقاش لك",
        "hi": "अपनी पहली चर्चा शुरू करें", "ja": "最初のディスカッションを始める",
        "ko": "첫 번째 토론 시작하기", "nl": "Start uw eerste discussie",
    },
    "Login": {
        "es": "Iniciar sesión", "fr": "Connexion", "de": "Anmelden",
        "pt": "Entrar", "zh": "登录", "ar": "تسجيل الدخول",
        "hi": "लॉगिन", "ja": "ログイン", "ko": "로그인", "nl": "Inloggen",
    },
    "Email": {
        "es": "Correo electrónico", "fr": "E-mail", "de": "E-Mail",
        "pt": "E-mail", "zh": "电子邮件", "ar": "البريد الإلكتروني",
        "hi": "ईमेल", "ja": "メール", "ko": "이메일", "nl": "E-mail",
    },
    "Password": {
        "es": "Contraseña", "fr": "Mot de passe", "de": "Passwort",
        "pt": "Senha", "zh": "密码", "ar": "كلمة المرور",
        "hi": "पासवर्ड", "ja": "パスワード", "ko": "비밀번호", "nl": "Wachtwoord",
    },
    "Forgot Password?": {
        "es": "¿Olvidaste tu contraseña?", "fr": "Mot de passe oublié ?", "de": "Passwort vergessen?",
        "pt": "Esqueceu a senha?", "zh": "忘记密码？", "ar": "نسيت كلمة المرور؟",
        "hi": "पासवर्ड भूल गए?", "ja": "パスワードをお忘れですか？", "ko": "비밀번호를 잊으셨나요?", "nl": "Wachtwoord vergeten?",
    },
    "Logging in\u2026": {
        "es": "Iniciando sesión\u2026", "fr": "Connexion en cours\u2026", "de": "Anmelden\u2026",
        "pt": "Entrando\u2026", "zh": "登录中\u2026", "ar": "جارٍ تسجيل الدخول\u2026",
        "hi": "लॉगिन हो रहा है\u2026", "ja": "ログイン中\u2026", "ko": "로그인 중\u2026", "nl": "Inloggen\u2026",
    },
    "Don't have an account?": {
        "es": "¿No tienes cuenta?", "fr": "Pas encore de compte ?", "de": "Noch kein Konto?",
        "pt": "Não tem uma conta?", "zh": "没有账户？", "ar": "ليس لديك حساب؟",
        "hi": "खाता नहीं है?", "ja": "アカウントをお持ちでないですか？", "ko": "계정이 없으신가요?", "nl": "Nog geen account?",
    },
    "Register": {
        "es": "Registrarse", "fr": "S'inscrire", "de": "Registrieren",
        "pt": "Registrar", "zh": "注册", "ar": "التسجيل",
        "hi": "रजिस्टर करें", "ja": "登録", "ko": "회원가입", "nl": "Registreren",
    },
    "Username": {
        "es": "Nombre de usuario", "fr": "Nom d'utilisateur", "de": "Benutzername",
        "pt": "Nome de usuário", "zh": "用户名", "ar": "اسم المستخدم",
        "hi": "उपयोगकर्ता नाम", "ja": "ユーザー名", "ko": "사용자 이름", "nl": "Gebruikersnaam",
    },
    "Verify you're human: What is %(num1)s + %(num2)s?": {
        "es": "Verifica que eres humano: ¿Cuánto es %(num1)s + %(num2)s?",
        "fr": "Vérifiez que vous êtes humain : Combien font %(num1)s + %(num2)s ?",
        "de": "Bestätigen Sie, dass Sie ein Mensch sind: Was ist %(num1)s + %(num2)s?",
        "pt": "Verifique que você é humano: Quanto é %(num1)s + %(num2)s?",
        "zh": "请验证您是人类：%(num1)s + %(num2)s 等于多少？",
        "ar": "تحقق من أنك إنسان: ما هو %(num1)s + %(num2)s؟",
        "hi": "सत्यापित करें कि आप इंसान हैं: %(num1)s + %(num2)s क्या है?",
        "ja": "人間であることを確認: %(num1)s + %(num2)s は？",
        "ko": "사람임을 확인하세요: %(num1)s + %(num2)s 는?", "nl": "Bevestig dat u een mens bent: Wat is %(num1)s + %(num2)s?",
    },
    "Already have an account?": {
        "es": "¿Ya tienes cuenta?", "fr": "Vous avez déjà un compte ?", "de": "Haben Sie bereits ein Konto?",
        "pt": "Já tem uma conta?", "zh": "已有账户？", "ar": "لديك حساب بالفعل؟",
        "hi": "पहले से खाता है?", "ja": "すでにアカウントをお持ちですか？", "ko": "이미 계정이 있으신가요?", "nl": "Heeft u al een account?",
    },
    "New": {
        "es": "Nuevo", "fr": "Nouveau", "de": "Neu",
        "pt": "Novo", "zh": "新建", "ar": "جديد",
        "hi": "नया", "ja": "新規", "ko": "새로 만들기", "nl": "Nieuw",
    },
    "Live public programmes with open discussions you can participate in.": {
        "es": "Programas públicos en vivo con debates abiertos en los que puedes participar.",
        "fr": "Programmes publics en direct avec des discussions ouvertes auxquelles vous pouvez participer.",
        "de": "Live-öffentliche Programme mit offenen Diskussionen, an denen Sie teilnehmen können.",
        "pt": "Programas públicos ao vivo com discussões abertas das quais você pode participar.",
        "zh": "您可以参与的实时公开项目和开放讨论。",
        "ar": "برامج عامة مباشرة مع نقاشات مفتوحة يمكنك المشاركة فيها.",
        "hi": "सार्वजनिक कार्यक्रम और खुली चर्चाएं जिनमें आप भाग ले सकते हैं।",
        "ja": "参加可能なオープンディスカッションを含む公開ライブプログラム。",
        "ko": "참여할 수 있는 열린 토론이 있는 라이브 공개 프로그램.",
        "nl": "Live publieke programma's met open discussies waaraan u kunt deelnemen.",
    },
}


def update_po_file(filepath, translations_for_lang):
    """Update a .po file with new translations."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Parse the file into blocks
    blocks = content.split('\n\n')
    updated_blocks = []

    for block in blocks:
        if not block.strip():
            updated_blocks.append(block)
            continue

        lines = block.split('\n')
        msgid = None
        msgstr_idx = None
        msgstr_val = None

        for i, line in enumerate(lines):
            if line.startswith('msgid '):
                msgid = line[6:].strip().strip('"')
            elif line.startswith('msgstr '):
                msgstr_idx = i
                msgstr_val = line[7:].strip().strip('"')

        # If we have an untranslated entry, fill it in
        if msgid and msgstr_idx is not None and not msgstr_val and msgid in translations_for_lang:
            translation = translations_for_lang[msgid]
            # Escape backslashes and quotes
            translation = translation.replace('\\', '\\\\').replace('"', '\\"')
            lines[msgstr_idx] = f'msgstr "{translation}"'
            block = '\n'.join(lines)

        updated_blocks.append(block)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n\n'.join(updated_blocks))


def main():
    translations_dir = 'translations'
    languages = ['es', 'fr', 'de', 'pt', 'zh', 'ar', 'hi', 'ja', 'ko', 'nl']

    for lang in languages:
        po_file = os.path.join(translations_dir, lang, 'LC_MESSAGES', 'messages.po')
        if not os.path.exists(po_file):
            print(f"  Skipping {lang} — file not found")
            continue

        # Build translations dict for this language
        lang_translations = {}
        for msgid, lang_map in TRANSLATIONS.items():
            if lang in lang_map:
                lang_translations[msgid] = lang_map[lang]

        update_po_file(po_file, lang_translations)
        print(f"  Updated {lang}")

    print("Done!")


if __name__ == '__main__':
    main()
