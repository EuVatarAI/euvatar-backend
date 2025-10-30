import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    base_dir: str
    static_dir: str
    upload_dir: str

    heygen_api_key: str
    heygen_default_avatar: str

    openai_api_key: str | None

    supabase_url: str
    supabase_service_role: str
    supabase_bucket: str

    app_host: str
    app_port: int
    app_debug: bool

    @staticmethod
    def load() -> "Settings":
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        root = os.path.abspath(os.path.join(base, ".."))
        static_dir = os.path.join(root, "public")
        upload_dir = os.path.join(root, "uploads")
        os.makedirs(upload_dir, exist_ok=True)

        heygen = os.getenv("HEYGEN_API_KEY")
        assert heygen, "Coloque HEYGEN_API_KEY no .env"

        supabase_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_SERVICE_ROLE")
        assert supabase_url and supabase_key, "Defina SUPABASE_URL e SUPABASE_SERVICE_ROLE no .env"

        return Settings(
            base_dir=root,
            static_dir=static_dir,
            upload_dir=upload_dir,
            heygen_api_key=heygen,
            heygen_default_avatar=os.getenv("HEYGEN_STREAMING_AVATAR", "Thaddeus_ProfessionalLook2_public"),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            supabase_url=supabase_url,
            supabase_service_role=supabase_key,
            supabase_bucket=os.getenv("SUPABASE_BUCKET", "avatar-media"),
            app_host=os.getenv("APP_HOST", "127.0.0.1"),
            app_port=int(os.getenv("APP_PORT", "5001")),
            app_debug=os.getenv("APP_DEBUG", "true").lower() == "true"
        )
