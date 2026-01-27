import os
from urllib.parse import urlparse
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Settings:
    base_dir: str
    static_dir: str
    upload_dir: str

    avatar_provider: str
    heygen_api_key: str | None
    liveavatar_api_key: str | None
    liveavatar_voice_id: str | None
    liveavatar_context_id: str | None
    heygen_default_avatar: str

    openai_api_key: str | None

    supabase_url: str
    supabase_service_role: str
    supabase_bucket: str

    api_token: str
    cors_origins: List[str]
    enable_debug_routes: bool
    upload_max_mb: int
    doc_fetch_allow_hosts: List[str]
    doc_fetch_max_bytes: int

    app_host: str
    app_port: int
    app_debug: bool

    # provider (heygen|liveavatar)
    use_livekit: bool
  
  

    @staticmethod
    def load() -> "Settings":
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        root = os.path.abspath(os.path.join(base, ".."))

        static_dir = os.path.join(root, "public")
        upload_dir = os.path.join(root, "uploads")
        os.makedirs(upload_dir, exist_ok=True)

        def _split_env_list(val: str | None) -> list[str]:
            return [v.strip() for v in (val or "").split(",") if v.strip()]

        app_debug_env = os.getenv("APP_DEBUG", "false").lower() == "true"
        
        use_livekit = os.getenv("HEYGEN_USE_LIVEKIT", "true").lower() == "true"
        avatar_provider = os.getenv("AVATAR_PROVIDER", "heygen").lower().strip()
       


        heygen = os.getenv("HEYGEN_API_KEY")
        liveavatar = os.getenv("LIVEAVATAR_API_KEY")
        if avatar_provider == "liveavatar":
            assert liveavatar, "Coloque LIVEAVATAR_API_KEY no .env"
        else:
            assert heygen, "Coloque HEYGEN_API_KEY no .env"

        supabase_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_SERVICE_ROLE")
        assert supabase_url and supabase_key, "Defina SUPABASE_URL e SUPABASE_SERVICE_ROLE no .env"

        api_token = os.getenv("APP_API_TOKEN")
        assert api_token, "Defina APP_API_TOKEN para habilitar autenticação no backend"

        cors_env = os.getenv("CORS_ORIGINS", "http://localhost:3000")
        cors_origins = _split_env_list(cors_env) or ["http://localhost:3000"]

        doc_hosts = _split_env_list(os.getenv("DOC_FETCH_ALLOW_HOSTS"))

        if supabase_url:
            host = (urlparse(supabase_url).hostname or "").strip()
            if host and host not in doc_hosts:
                doc_hosts.append(host)

        return Settings(
            base_dir=root,
            static_dir=static_dir,
            upload_dir=upload_dir,

            avatar_provider=avatar_provider,
            heygen_api_key=heygen,
            liveavatar_api_key=liveavatar,
            liveavatar_voice_id=os.getenv("LIVEAVATAR_VOICE_ID"),
            liveavatar_context_id=os.getenv("LIVEAVATAR_CONTEXT_ID"),
            heygen_default_avatar=os.getenv(
                "HEYGEN_STREAMING_AVATAR",
                "Thaddeus_ProfessionalLook2_public"
            ),

            openai_api_key=os.getenv("OPENAI_API_KEY"),

            supabase_url=supabase_url,
            supabase_service_role=supabase_key,
            supabase_bucket=os.getenv("SUPABASE_BUCKET", "avatar-media"),

            api_token=api_token,
            cors_origins=cors_origins,
            enable_debug_routes=os.getenv("ENABLE_DEBUG_ROUTES", "false").lower() == "true",
            upload_max_mb=int(os.getenv("UPLOAD_MAX_MB", "5")),
            doc_fetch_allow_hosts=doc_hosts,
            doc_fetch_max_bytes=int(os.getenv("DOC_FETCH_MAX_BYTES", "512000")),

            app_host=os.getenv("APP_HOST", "127.0.0.1"),
            app_port=int(os.getenv("APP_PORT", "5001")),
            app_debug=app_debug_env,

            # 🔥 AQUI ESTAVA O BUG
            use_livekit=use_livekit,
            

           
        )
