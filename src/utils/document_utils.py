import os
import json
from typing import List, Dict, Optional


class DocumentationBuilder:
    """
    Utility class to build dynamic documentation pages based on available modules.
    """
    
    def __init__(self, project_root: str):
        """
        Initialize the documentation builder.
        
        Args:
            project_root: Path to the root directory of the Omnipet project
        """
        self.project_root = project_root
        self.modules_dir = os.path.join(project_root, "modules")
        self.docs_dir = os.path.join(project_root, "Documentation")
        # The page's skeleton, with a marker for the CSS and one for the list.
        # It lived under the long-gone game/core/utils, so every start logged
        # "Template not found" and the page stayed as built in 2025 (P-07).
        self.template_path = os.path.join(self.docs_dir, "templates", "module-guide_template.html")
        self.output_path = os.path.join(self.docs_dir, "pages", "module-guide.html")
    
    def scan_modules(self) -> List[Dict[str, Optional[str]]]:
        """
        Scan the modules directory for available modules with documentation.
        
        Returns:
            List of module dictionaries containing name, version, logo path, and doc path
        """
        modules = []
        
        if not os.path.exists(self.modules_dir):
            return modules
        
        for module_name in sorted(os.listdir(self.modules_dir)):
            module_path = os.path.join(self.modules_dir, module_name)
            
            # Skip if not a directory
            if not os.path.isdir(module_path):
                continue
            
            # Check for documentation
            doc_index = os.path.join(module_path, "documentation", "index.html")
            if not os.path.exists(doc_index):
                continue
            
            # Get module info
            module_info = self._get_module_info(module_path, module_name)
            if module_info:
                modules.append(module_info)
        
        return modules
    
    def _get_module_info(self, module_path: str, module_name: str) -> Optional[Dict[str, Optional[str]]]:
        """
        Extract module information from module.json and check for required files.
        
        Args:
            module_path: Path to the module directory
            module_name: Name of the module
            
        Returns:
            Dictionary with module information or None if invalid
        """
        # Check for logo
        logo_path = os.path.join(module_path, "logo.png")
        flag_path = os.path.join(module_path, "Flag.png")
        
        # Use logo.png if available, otherwise Flag.png
        icon_file = None
        if os.path.exists(logo_path):
            icon_file = "logo.png"
        elif os.path.exists(flag_path):
            icon_file = "Flag.png"
        
        if not icon_file:
            return None
        
        # Try to get module metadata
        module_json_path = os.path.join(module_path, "module.json")
        version = "Unknown"
        description = ""
        from utils.asset_utils import open_json, resolve_path
        resolved_path = resolve_path(module_json_path)
        if os.path.exists(resolved_path):
            try:
                with open_json(module_json_path) as f:
                    module_data = json.load(f)
                    version = module_data.get("version", "Unknown")
                    description = module_data.get("description", "")
            except (json.JSONDecodeError, IOError):
                pass
        
        return {
            "name": module_name,
            "version": version,
            "description": description,
            "icon_path": f"../../modules/{module_name}/{icon_file}",
            "doc_path": f"../../modules/{module_name}/documentation/index.html"
        }
    
    def generate_module_cards_html(self, modules: List[Dict[str, Optional[str]]]) -> str:
        """
        Generate HTML for module cards.
        
        Args:
            modules: List of module dictionaries
            
        Returns:
            HTML string for module cards
        """
        if not modules:
            return """
            <div class="no-modules-message">
                <h3>No Module Documentation Found</h3>
                <p>To add module documentation:</p>
                <ul>
                    <li>Create a <code>documentation</code> folder in your module directory</li>
                    <li>Add an <code>index.html</code> file with your module's documentation</li>
                    <li>Ensure your module has a <code>logo.png</code> or <code>Flag.png</code> file</li>
                </ul>
                <p>You can find modules in the <code>modules</code> folder of your Omnipet installation.</p>
            </div>
            """
        
        cards_html = '<div class="module-list">'
        
        for module in modules:
            cards_html += f"""
            <div class="module-card">
                <a href="{module['doc_path']}" title="Open {module['name']} documentation">
                    <div class="module-icon">
                        <img src="{module['icon_path']}" alt="{module['name']} icon" class="module-logo" 
                             onerror="this.style.display='none'; this.nextElementSibling.style.display='block';" />
                        <div class="module-logo-fallback" style="display: none;">{module['name'][0]}</div>
                    </div>
                    <div class="module-info">
                        <div class="module-name">{module['name']}</div>
                        <div class="module-version">v{module['version']}</div>
                        {f'<div class="module-description">{module["description"][:60]}{"..." if len(module["description"]) > 60 else ""}</div>' if module['description'] else ''}
                    </div>
                </a>
            </div>
            """
        
        cards_html += '</div>'
        return cards_html
    
    def get_module_guide_css(self) -> str:
        """
        Return CSS styles for the module guide.
        
        Returns:
            CSS string for module guide styling
        """
        return """
        <style>
            .module-list {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
                gap: 24px;
                margin-top: 32px;
            }
            
            .module-card {
                background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%);
                border-radius: 16px;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
                transition: all 0.3s ease;
                overflow: hidden;
                border: 2px solid transparent;
            }
            
            .module-card:hover {
                transform: translateY(-4px);
                box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
                border-color: #3b82f6;
            }
            
            .module-card a {
                display: block;
                padding: 20px;
                text-decoration: none;
                color: inherit;
                height: 100%;
            }
            
            .module-icon {
                text-align: center;
                margin-bottom: 16px;
                position: relative;
            }
            
            .module-logo {
                width: 80px;
                height: 80px;
                object-fit: contain;
                border-radius: 12px;
                background: rgba(255, 255, 255, 0.8);
                padding: 8px;
            }
            
            .module-logo-fallback {
                width: 80px;
                height: 80px;
                background: linear-gradient(135deg, #3b82f6, #1d4ed8);
                color: white;
                border-radius: 12px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 32px;
                font-weight: bold;
                margin: 0 auto;
            }
            
            .module-info {
                text-align: center;
            }
            
            .module-name {
                font-size: 1.25em;
                font-weight: bold;
                color: #1e293b;
                margin-bottom: 4px;
            }
            
            .module-version {
                font-size: 0.9em;
                color: #64748b;
                margin-bottom: 8px;
                font-family: monospace;
                background: rgba(59, 130, 246, 0.1);
                padding: 2px 8px;
                border-radius: 12px;
                display: inline-block;
            }
            
            .module-description {
                font-size: 0.85em;
                color: #475569;
                line-height: 1.4;
                margin-top: 8px;
            }
            
            .no-modules-message {
                text-align: center;
                padding: 48px 24px;
                background: #f8fafc;
                border-radius: 12px;
                border: 2px dashed #cbd5e1;
                margin-top: 32px;
            }
            
            .no-modules-message h3 {
                color: #374151;
                margin-bottom: 16px;
            }
            
            .no-modules-message p {
                color: #6b7280;
                margin-bottom: 16px;
            }
            
            .no-modules-message ul {
                text-align: left;
                display: inline-block;
                color: #6b7280;
            }
            
            .no-modules-message code {
                background: #e5e7eb;
                padding: 2px 6px;
                border-radius: 4px;
                font-family: monospace;
            }
        </style>
        """
    
    def build_module_guide(self) -> bool:
        """
        Build the module guide HTML page by scanning modules and updating the template.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Read template
            if not os.path.exists(self.template_path):
                print(f"Template not found: {self.template_path}")
                return False
            
            with open(self.template_path, 'r', encoding='utf-8') as f:
                template_content = f.read()
            
            # Scan modules
            modules = self.scan_modules()
            
            # Generate module cards HTML
            module_cards_html = self.generate_module_cards_html(modules)
            
            # The template marks where the CSS and the list go. Splicing the
            # list in by searching for closing tags once wrote a second copy
            # of the page into it.
            final_content = (template_content
                             .replace('<!-- MODULE_GUIDE_CSS -->', self.get_module_guide_css())
                             .replace('<!-- MODULE_LIST -->', module_cards_html))

            # Ensure output directory exists
            os.makedirs(os.path.dirname(self.output_path), exist_ok=True)

            # Only when something changed: the page is rebuilt at every start
            try:
                with open(self.output_path, 'r', encoding='utf-8') as f:
                    if f.read() == final_content:
                        return True
            except OSError:
                pass
            with open(self.output_path, 'w', encoding='utf-8') as f:
                f.write(final_content)
            
            print(f"Module guide built successfully with {len(modules)} modules")
            return True
            
        except Exception as e:
            print(f"Error building module guide: {e}")
            return False


def build_module_documentation(project_root: str) -> bool:
    """
    Convenience function to build module documentation.
    
    Args:
        project_root: Path to the root directory of the Omnipet project
        
    Returns:
        True if successful, False otherwise
    """
    builder = DocumentationBuilder(project_root)
    return builder.build_module_guide()
