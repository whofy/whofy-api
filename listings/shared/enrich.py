import re

REMOTE_RE = re.compile(r"\bremote\b", re.IGNORECASE)
HYBRID_RE = re.compile(r"\bhybrid\b", re.IGNORECASE)
ONSITE_RE = re.compile(r"\b(?:on[\s-]?site|in[\s-]?office|in[\s-]?person)\b", re.IGNORECASE)

_YEARS_RE = re.compile(r"(\d+)\+?\s*(?:years?|yrs?)", re.IGNORECASE)
_SENIOR_RE = re.compile(r"\b(?:senior|sr\.?|staff|principal|lead|director|head)\b", re.IGNORECASE)
_JUNIOR_RE = re.compile(r"\b(?:junior|jr\.?|associate)\b", re.IGNORECASE)
_INTERN_RE = re.compile(r"\b(?:intern|internship|trainee|apprentice|co-?op)\b", re.IGNORECASE)
_ENTRY_RE = re.compile(r"\b(?:entry[\s-]?level|graduate|fresher|new[\s-]?grad)\b", re.IGNORECASE)

SKILL_VOCAB = [
    # ── Programming Languages ──
    "Python", "JavaScript", "TypeScript", "Java", "C++", "C#", "Go", "Golang",
    "Rust", "Ruby", "PHP", "Kotlin", "Swift", "Scala", "R", "MATLAB",
    "Perl", "Lua", "Haskell", "Erlang", "Elixir", "Clojure", "F#",
    "Groovy", "Dart", "Julia", "Zig", "Nim", "OCaml", "Fortran", "COBOL",
    "Assembly", "Bash", "Shell", "PowerShell", "VBA", "Delphi", "Pascal",
    "Objective-C", "ABAP", "Apex", "Solidity", "Vyper", "Move", "Cairo",
    "Prolog", "Lisp", "Scheme", "Racket", "Crystal", "V", "Ada",
    "VHDL", "Verilog", "SystemVerilog", "LabVIEW", "SAS", "SPSS", "Stata",

    # ── Frontend Frameworks & Libraries ──
    "React", "Angular", "Vue", "Svelte", "Next.js", "Nuxt.js", "Gatsby",
    "Remix", "Astro", "SolidJS", "Qwik", "Alpine.js", "Lit", "Stencil",
    "Ember.js", "Backbone.js", "jQuery", "Preact", "Inferno",
    "Redux", "MobX", "Zustand", "Recoil", "XState", "Jotai", "Valtio",
    "React Query", "TanStack Query", "SWR", "Apollo Client",
    "Tailwind", "Bootstrap", "Material UI", "Chakra UI", "Ant Design",
    "Styled Components", "Emotion", "Radix UI", "Shadcn", "DaisyUI",
    "HTML", "CSS", "Sass", "LESS", "PostCSS", "CSS Modules",
    "Webpack", "Vite", "Rollup", "Parcel", "esbuild", "Turbopack", "SWC",
    "Babel", "ESLint", "Prettier", "Storybook",
    "Three.js", "D3.js", "Chart.js", "Highcharts", "ECharts", "Recharts",
    "Leaflet", "Mapbox", "Cesium", "PixiJS", "Phaser", "Babylon.js",
    "HTMX", "Turbo", "Stimulus", "Hotwire",
    "WebAssembly", "WASM", "WebGL", "WebGPU", "WebRTC", "WebSocket",
    "PWA", "Service Worker", "Web Components", "Shadow DOM",

    # ── Backend Frameworks ──
    "Node.js", "Express", "Fastify", "NestJS", "Koa", "Hapi",
    "Django", "Flask", "FastAPI", "Tornado", "Pyramid", "Sanic",
    "Spring", "Spring Boot", "Quarkus", "Micronaut", "Vert.x", "Dropwizard",
    "Rails", "Sinatra", "Hanami",
    ".NET", "ASP.NET", "Blazor", "Entity Framework",
    "Laravel", "Symfony", "CodeIgniter", "CakePHP", "Yii", "Slim",
    "Gin", "Echo", "Fiber", "Chi", "Buffalo",
    "Actix", "Axum", "Rocket", "Warp", "Tokio",
    "Phoenix", "Ecto",
    "Ktor", "Micronaut",
    "Deno", "Bun",

    # ── API & Communication ──
    "GraphQL", "REST", "gRPC", "SOAP", "WebSocket", "SSE",
    "OpenAPI", "Swagger", "Postman", "Insomnia",
    "Apollo", "Hasura", "Prisma", "tRPC", "Hono",
    "Protocol Buffers", "Protobuf", "Thrift", "Avro",
    "JSON", "XML", "YAML", "TOML",
    "OAuth", "JWT", "SAML", "OIDC", "Auth0", "Okta", "Keycloak",
    "LDAP", "Active Directory", "Kerberos",

    # ── Databases — Relational ──
    "SQL", "PostgreSQL", "MySQL", "MariaDB", "SQLite", "Oracle",
    "SQL Server", "MSSQL", "DB2", "CockroachDB", "TiDB", "YugabyteDB",
    "Vitess", "PlanetScale", "Neon", "Supabase",
    "Aurora", "AlloyDB", "Cloud SQL", "RDS",

    # ── Databases — NoSQL & NewSQL ──
    "MongoDB", "Redis", "Elasticsearch", "Cassandra", "DynamoDB",
    "Couchbase", "CouchDB", "HBase", "ScyllaDB", "ArangoDB",
    "Neo4j", "JanusGraph", "TigerGraph", "Neptune", "Dgraph",
    "InfluxDB", "TimescaleDB", "QuestDB", "ClickHouse", "Druid",
    "Firebase", "Firestore", "Realm", "RethinkDB",
    "Memcached", "Hazelcast", "Aerospike",
    "Pinecone", "Weaviate", "Milvus", "Qdrant", "Chroma", "pgvector",
    "FaunaDB", "SurrealDB", "EdgeDB", "Turso",

    # ── Cloud Platforms & Services ──
    "AWS", "Azure", "GCP", "Oracle Cloud", "IBM Cloud", "Alibaba Cloud",
    "DigitalOcean", "Linode", "Vultr", "Hetzner", "OVH",
    "Heroku", "Vercel", "Netlify", "Render", "Railway", "Fly.io",
    "Cloudflare", "Cloudflare Workers", "Akamai", "Fastly",
    "EC2", "S3", "Lambda", "ECS", "EKS", "Fargate", "SQS", "SNS",
    "API Gateway", "CloudFront", "Route 53", "IAM", "VPC",
    "Azure Functions", "Azure DevOps", "Cosmos DB",
    "Cloud Functions", "Cloud Run", "BigQuery", "Cloud Storage",
    "App Engine", "Compute Engine", "Cloud Pub/Sub",

    # ── DevOps & Infrastructure ──
    "Docker", "Kubernetes", "Terraform", "Ansible", "Puppet", "Chef",
    "Vagrant", "Packer", "Consul", "Vault", "Nomad",
    "Helm", "Kustomize", "ArgoCD", "Flux", "Spinnaker",
    "Istio", "Linkerd", "Envoy", "Traefik", "HAProxy",
    "Nginx", "Apache", "Caddy", "IIS",
    "Jenkins", "GitHub Actions", "GitLab CI", "CircleCI", "Travis CI",
    "Drone CI", "TeamCity", "Bamboo", "Azure Pipelines", "Buildkite",
    "CI/CD", "Git", "GitHub", "GitLab", "Bitbucket", "SVN",
    "Linux", "Ubuntu", "CentOS", "RHEL", "Debian", "Alpine",
    "Windows Server", "macOS",
    "Prometheus", "Grafana", "Datadog", "New Relic", "Dynatrace",
    "Splunk", "ELK Stack", "Logstash", "Kibana", "Fluentd", "Loki",
    "PagerDuty", "OpsGenie", "VictorOps",
    "Nagios", "Zabbix", "Icinga", "Sensu",
    "SonarQube", "Snyk", "Trivy", "Aqua", "Twistlock",
    "Pulumi", "CloudFormation", "CDK", "Crossplane",
    "OpenStack", "VMware", "vSphere", "Proxmox", "Hyper-V",
    "Rancher", "OpenShift", "Tanzu", "Portainer",

    # ── Data Engineering & Big Data ──
    "Data Science", "Data Engineering", "Data Analytics",
    "ETL", "ELT", "Data Pipeline", "Data Warehouse", "Data Lake",
    "Spark", "PySpark", "Hadoop", "HDFS", "MapReduce", "Hive", "Pig",
    "Airflow", "Dagster", "Prefect", "Luigi", "dbt", "Fivetran", "Airbyte",
    "Snowflake", "Databricks", "Redshift", "BigQuery", "Synapse",
    "Delta Lake", "Apache Iceberg", "Apache Hudi",
    "Flink", "Storm", "Beam", "Samza", "Kinesis",
    "Presto", "Trino", "Athena", "Starburst",
    "Kafka", "RabbitMQ", "Pulsar", "NATS", "ActiveMQ", "ZeroMQ",
    "Kafka Streams", "Kafka Connect", "Debezium", "CDC",
    "Celery", "Sidekiq", "Bull", "BullMQ",
    "Pandas", "NumPy", "SciPy", "Polars", "Dask", "Vaex", "Modin",
    "Arrow", "Parquet", "ORC", "Avro",

    # ── AI & Machine Learning ──
    "Machine Learning", "Deep Learning", "Artificial Intelligence",
    "TensorFlow", "PyTorch", "Keras", "JAX", "MXNet", "Caffe",
    "Scikit-learn", "XGBoost", "LightGBM", "CatBoost", "H2O",
    "NLP", "Natural Language Processing", "Computer Vision",
    "LLM", "Large Language Model", "GPT", "BERT", "Transformer",
    "LangChain", "LlamaIndex", "Semantic Kernel", "AutoGen",
    "RAG", "Retrieval Augmented Generation",
    "Hugging Face", "OpenAI", "Anthropic", "Cohere", "Mistral",
    "Stable Diffusion", "Midjourney", "DALL-E",
    "MLflow", "Kubeflow", "MLOps", "Feature Store",
    "Weights & Biases", "Neptune", "Comet", "DVC",
    "ONNX", "TensorRT", "Triton", "TFLite", "CoreML",
    "SageMaker", "Vertex AI", "Azure ML", "Bedrock",
    "OpenCV", "YOLO", "Detectron", "MediaPipe",
    "SpaCy", "NLTK", "Gensim", "Rasa", "Dialogflow",
    "Reinforcement Learning", "Federated Learning",
    "Neural Network", "CNN", "RNN", "LSTM", "GAN", "VAE",
    "Time Series", "Anomaly Detection", "Recommendation System",
    "A/B Testing", "Bayesian", "Statistical Modeling",
    "CUDA", "cuDNN", "ROCm", "Triton Inference",

    # ── Mobile Development ──
    "iOS", "Android", "React Native", "Flutter", "Xamarin", "MAUI",
    "SwiftUI", "UIKit", "Jetpack Compose", "Kotlin Multiplatform",
    "Ionic", "Capacitor", "Cordova", "PhoneGap", "Expo",
    "App Store", "Google Play", "TestFlight", "Firebase",
    "Core Data", "Room", "Realm", "SQLite",
    "ARKit", "ARCore", "Core ML", "ML Kit",
    "Push Notifications", "Deep Linking",

    # ── Testing & QA ──
    "Jest", "Cypress", "Selenium", "Pytest", "JUnit", "TestNG",
    "Playwright", "Puppeteer", "WebdriverIO", "Appium",
    "Mocha", "Chai", "Jasmine", "Karma", "Vitest",
    "RSpec", "Capybara", "Minitest",
    "xUnit", "NUnit", "MSTest",
    "Robot Framework", "Cucumber", "Behave", "SpecFlow",
    "Postman", "Newman", "REST Assured", "Karate",
    "k6", "Gatling", "JMeter", "Locust", "Artillery",
    "SonarQube", "Codecov", "Coveralls",
    "Allure", "TestRail", "Zephyr",
    "TDD", "BDD", "Unit Testing", "Integration Testing",
    "End-to-End Testing", "Load Testing", "Performance Testing",
    "Chaos Engineering", "Fault Injection",
    "Mutation Testing", "Contract Testing", "Pact",

    # ── Security & Compliance ──
    "Cybersecurity", "Information Security", "AppSec",
    "OWASP", "Penetration Testing", "Pen Testing",
    "SAST", "DAST", "IAST", "SCA",
    "Burp Suite", "Metasploit", "Nmap", "Wireshark",
    "Nessus", "Qualys", "Rapid7", "CrowdStrike", "SentinelOne",
    "WAF", "IDS", "IPS", "SIEM", "SOAR",
    "Zero Trust", "PKI", "SSL", "TLS", "mTLS",
    "SOC 2", "ISO 27001", "GDPR", "HIPAA", "PCI DSS", "FedRAMP",
    "HashiCorp Vault", "CyberArk", "Secrets Management",
    "IAM", "RBAC", "ABAC", "PAM",
    "Encryption", "AES", "RSA", "Cryptography",
    "Threat Modeling", "Incident Response", "Digital Forensics",
    "DevSecOps", "Shift Left", "Security Automation",

    # ── Networking & Infrastructure ──
    "TCP/IP", "DNS", "HTTP", "HTTPS", "SSH", "FTP", "SMTP",
    "BGP", "OSPF", "MPLS", "VLAN", "VPN", "SD-WAN",
    "Cisco", "Juniper", "Palo Alto", "Fortinet", "F5",
    "CDN", "Load Balancer", "Reverse Proxy",
    "IPv4", "IPv6", "Subnetting", "Firewall",
    "SDN", "NFV", "5G", "IoT",
    "SNMP", "NetFlow", "sFlow",

    # ── Game Development ──
    "Unity", "Unreal Engine", "Godot", "CryEngine",
    "C++", "Blueprints", "Shader", "HLSL", "GLSL",
    "DirectX", "OpenGL", "Vulkan", "Metal",
    "Photon", "Mirror", "Netcode",
    "Game Design", "Level Design", "3D Modeling",
    "Blender", "Maya", "3ds Max", "ZBrush",

    # ── Design & Creative Tools ──
    "Figma", "Sketch", "Adobe XD", "InVision", "Framer",
    "UI/UX", "UI Design", "UX Design", "UX Research",
    "Photoshop", "Illustrator", "After Effects", "Premiere Pro",
    "InDesign", "Lightroom", "Canva",
    "Design System", "Wireframing", "Prototyping",
    "User Research", "Usability Testing", "Accessibility", "WCAG",
    "Responsive Design", "Mobile First",

    # ── CMS & E-commerce ──
    "WordPress", "Drupal", "Joomla", "Ghost", "Strapi", "Contentful",
    "Sanity", "Prismic", "Directus", "KeystoneJS",
    "Shopify", "Magento", "WooCommerce", "BigCommerce",
    "Medusa", "Saleor", "CommerceTools",

    # ── ERP & Enterprise ──
    "SAP", "SAP HANA", "SAP S/4HANA", "SAP FICO", "SAP MM", "SAP SD",
    "Salesforce", "ServiceNow", "Workday", "Oracle EBS", "PeopleSoft",
    "Dynamics 365", "NetSuite", "HubSpot", "Zoho",
    "ABAP", "Apex", "Lightning", "Visualforce",
    "MuleSoft", "Boomi", "Informatica", "Talend",
    "BPM", "RPA", "UiPath", "Automation Anywhere", "Blue Prism",

    # ── BI & Analytics ──
    "Tableau", "Power BI", "Looker", "Metabase", "Superset",
    "QlikView", "Qlik Sense", "Sisense", "Domo",
    "Google Analytics", "Adobe Analytics", "Mixpanel", "Amplitude",
    "Segment", "Snowplow", "Heap", "FullStory", "Hotjar",
    "Google Tag Manager", "Optimizely", "LaunchDarkly",
    "Excel", "Google Sheets", "VBA",

    # ── Project Management & Collaboration ──
    "Jira", "Confluence", "Trello", "Asana", "Monday.com",
    "Linear", "Notion", "ClickUp", "Basecamp", "Shortcut",
    "Agile", "Scrum", "Kanban", "SAFe", "Lean",
    "Product Management", "Project Management", "PMP",
    "Slack", "Microsoft Teams", "Zoom", "Discord",
    "Miro", "FigJam", "Lucidchart",

    # ── Blockchain & Web3 ──
    "Solidity", "Blockchain", "Web3", "Ethereum", "Bitcoin",
    "Smart Contract", "DeFi", "NFT", "DAO",
    "Hardhat", "Truffle", "Foundry", "Brownie",
    "ethers.js", "web3.js", "wagmi", "viem",
    "IPFS", "The Graph", "Chainlink", "Polygon", "Solana",
    "Cosmos", "Polkadot", "Avalanche", "Arbitrum", "Optimism",
    "Rust", "Anchor", "Move",
    "MetaMask", "WalletConnect",

    # ── Embedded & Hardware ──
    "Embedded Systems", "Firmware", "RTOS", "FreeRTOS", "Zephyr",
    "Arduino", "Raspberry Pi", "ESP32", "STM32", "ARM",
    "VHDL", "Verilog", "SystemVerilog", "FPGA", "ASIC",
    "PCB Design", "Altium", "KiCad", "Eagle",
    "SPI", "I2C", "UART", "CAN", "Modbus", "MQTT",
    "ROS", "ROS2", "Robotics", "PLC", "SCADA",
    "LabVIEW", "Simulink", "AutoCAD", "SolidWorks", "CATIA",

    # ── GIS & Geospatial ──
    "GIS", "ArcGIS", "QGIS", "PostGIS", "GeoPandas",
    "Mapbox", "Leaflet", "Google Maps API", "OpenStreetMap",
    "Remote Sensing", "Spatial Analysis",

    # ── Miscellaneous / Architecture ──
    "Microservices", "System Design", "Distributed Systems",
    "Event-Driven", "CQRS", "Event Sourcing", "Domain-Driven Design",
    "Monolith", "Serverless", "Edge Computing",
    "Low-Code", "No-Code", "Retool", "Appsmith",
    "Stripe", "Twilio", "SendGrid", "Plaid",
    "ElasticSearch", "Algolia", "Meilisearch", "Typesense",
    "Socket.IO", "SignalR",
    "Terraform", "Infrastructure as Code", "GitOps",
    "Site Reliability", "SRE", "Observability", "Monitoring",
    "Technical Writing", "Documentation", "API Documentation",
]
_SKILL_RES = [(skill, re.compile(r"\b" + re.escape(skill) + r"\b", re.IGNORECASE)) for skill in SKILL_VOCAB]

MAX_EXTRACTED_SKILLS = 15


def detect_work_type(title: str, location: str, description: str) -> str:
    text = f"{title} {location}"
    if HYBRID_RE.search(text):
        return "Hybrid"
    if REMOTE_RE.search(text):
        return "Remote"
    if ONSITE_RE.search(text):
        return "On-site"
    desc_head = description[:500] if description else ""
    if HYBRID_RE.search(desc_head):
        return "Hybrid"
    if REMOTE_RE.search(desc_head):
        return "Remote"
    if ONSITE_RE.search(desc_head):
        return "On-site"
    return "On-site"


def detect_experience(title: str, description: str) -> str:
    if _INTERN_RE.search(title):
        return "Internship"
    if _ENTRY_RE.search(title):
        return "Entry Level"
    if _JUNIOR_RE.search(title):
        return "Junior"
    if _SENIOR_RE.search(title):
        return "Senior"

    desc_head = description[:800] if description else ""
    m = _YEARS_RE.search(desc_head)
    if m:
        yrs = int(m.group(1))
        if yrs <= 1:
            return "Entry Level"
        if yrs <= 3:
            return "Junior"
        if yrs <= 6:
            return "Mid Level"
        return "Senior"

    if _INTERN_RE.search(desc_head):
        return "Internship"
    if _ENTRY_RE.search(desc_head):
        return "Entry Level"
    if _JUNIOR_RE.search(desc_head):
        return "Junior"
    if _SENIOR_RE.search(desc_head):
        return "Senior"

    return "Mid Level"


def extract_required_skills(title: str, description: str) -> list[str]:
    haystack = f"{title} {description}"
    found = []
    for skill, pattern in _SKILL_RES:
        if pattern.search(haystack):
            found.append(skill)
        if len(found) >= MAX_EXTRACTED_SKILLS:
            break
    return found


def bake_required_skills(description: str, required_skills: list[str]) -> str:
    if not required_skills:
        return description
    block = "Required skills:\n" + "\n".join(f"• {s}" for s in required_skills)
    return f"{description}\n\n{block}" if description else block
