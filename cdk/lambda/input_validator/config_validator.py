import json
import os
from typing import Dict, Any, Optional, List, Union
from copy import deepcopy


class ConfigValidator:
    """
    Configuration validator for P&ID processing pipeline.
    Loads default configuration and validates parameters.
    """
    
    def __init__(self, config_file_path: Optional[str] = None):
        """
        Initialize the config validator.
        
        Args:
            config_file_path: Path to default config JSON file. If None, looks in same directory.
        """
        if config_file_path is None:
            config_file_path = os.path.join(os.path.dirname(__file__), 'default_config.json')
        
        self.config_file_path = config_file_path
        self._default_config = None
        self._validation_schemas = self._create_validation_schemas()
    
    def load_default_config(self) -> Dict[str, Any]:
        """Load default configuration from JSON file."""
        if self._default_config is None:
            try:
                with open(self.config_file_path, 'r') as f:
                    self._default_config = json.load(f)
            except FileNotFoundError:
                raise ValueError(f"Default config file not found: {self.config_file_path}")
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in config file: {str(e)}")
        
        return deepcopy(self._default_config)
    
    def get_merged_config(self, stage: str, user_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Get merged configuration for a specific processing stage.
        
        Args:
            stage: Processing stage name (e.g., 'line_detection', 'graph_generation')
            user_config: User-provided configuration to override defaults
            
        Returns:
            Merged configuration dictionary
        """
        default_config = self.load_default_config()
        
        if stage not in default_config:
            raise ValueError(f"Unknown processing stage: {stage}")
        
        stage_config = deepcopy(default_config[stage])
        
        if user_config:
            stage_config = self._deep_merge(stage_config, user_config)
        
        # Validate the merged configuration
        validation_errors = self.validate_config(stage, stage_config)
        if validation_errors:
            raise ValueError(f"Configuration validation failed for {stage}: {validation_errors}")
        
        return stage_config
    
    def validate_config(self, stage: str, config: Dict[str, Any]) -> List[str]:
        """
        Validate configuration for a specific stage.
        
        Args:
            stage: Processing stage name
            config: Configuration to validate
            
        Returns:
            List of validation error messages (empty if valid)
        """
        if stage not in self._validation_schemas:
            return [f"No validation schema for stage: {stage}"]
        
        schema = self._validation_schemas[stage]
        errors = []
        
        errors.extend(self._validate_against_schema(config, schema, path=stage))
        
        return errors
    
    def _deep_merge(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Deep merge two dictionaries, with override taking precedence."""
        result = deepcopy(base)
        
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = deepcopy(value)
        
        return result
    
    def _validate_against_schema(self, config: Dict[str, Any], schema: Dict[str, Any], 
                                path: str = "") -> List[str]:
        """Validate configuration against schema."""
        errors = []
        
        # Check required fields
        for field, field_schema in schema.items():
            field_path = f"{path}.{field}" if path else field
            
            if field not in config:
                if field_schema.get('required', False):
                    errors.append(f"Missing required field: {field_path}")
                continue
            
            value = config[field]
            
            # Type validation
            expected_type = field_schema.get('type')
            if expected_type and not self._check_type(value, expected_type):
                errors.append(f"Invalid type for {field_path}: expected {expected_type}, got {type(value).__name__}")
                continue
            
            # Range validation for numeric types
            if isinstance(value, (int, float)):
                min_val = field_schema.get('min')
                max_val = field_schema.get('max')
                
                if min_val is not None and value < min_val:
                    errors.append(f"Value too small for {field_path}: {value} < {min_val}")
                
                if max_val is not None and value > max_val:
                    errors.append(f"Value too large for {field_path}: {value} > {max_val}")
            
            # Enum validation
            allowed_values = field_schema.get('allowed')
            if allowed_values and value not in allowed_values:
                errors.append(f"Invalid value for {field_path}: {value} not in {allowed_values}")
            
            # Nested object validation
            if isinstance(value, dict) and 'schema' in field_schema:
                errors.extend(self._validate_against_schema(value, field_schema['schema'], field_path))
        
        return errors
    
    def _check_type(self, value: Any, expected_type: str) -> bool:
        """Check if value matches expected type."""
        type_map = {
            'int': int,
            'float': (int, float),  # Allow int for float fields
            'str': str,
            'bool': bool,
            'dict': dict,
            'list': list
        }
        
        expected_python_type = type_map.get(expected_type)
        if expected_python_type is None:
            return True  # Unknown type, skip validation
        
        return isinstance(value, expected_python_type)
    
    def _create_validation_schemas(self) -> Dict[str, Dict[str, Any]]:
        """Create validation schemas for each processing stage."""
        return {
            'notes_processing': {
                'manual_coordinates': {
                    'type': 'dict',
                    'schema': {
                        'x': {'type': 'int', 'min': 0},
                        'y': {'type': 'int', 'min': 0},
                        'width': {'type': 'int', 'min': -1},
                        'height': {'type': 'int', 'min': -1}
                    }
                },
                'remove_notes_section': {'type': 'bool'},
                'frame_config': {
                    'type': 'dict',
                    'schema': {
                        'remove_frame': {'type': 'bool'},
                        'frame_detection_sensitivity': {'type': 'float', 'min': 0.0, 'max': 1.0},
                        'min_frame_thickness': {'type': 'int', 'min': 1},
                        'max_frame_thickness': {'type': 'int', 'min': 1},
                        'edge_margin_ratio': {'type': 'float', 'min': 0.0, 'max': 1.0},
                        'safety_margin': {'type': 'int', 'min': 0},
                        'min_line_length_ratio': {'type': 'float', 'min': 0.0, 'max': 1.0}
                    }
                }
            },
            'line_detection': {
                'max_line_gap': {'type': 'int', 'min': 1},
                'threshold': {'type': 'int', 'min': 1},
                'min_line_length': {'type': 'int', 'min': 1},
                'rho': {'type': 'float', 'min': 0.1},
                'theta_param': {'type': 'int', 'min': 1, 'max': 360},
                'enable_thinning': {'type': 'bool'},
                'postprocess_params': {
                    'type': 'dict',
                    'schema': {
                        'merge_distance_threshold': {'type': 'float', 'min': 0.0, 'max': 1.0},
                        'angular_tolerance': {'type': 'float', 'min': 0.0, 'max': 180.0},
                        'min_line_length': {'type': 'float', 'min': 0.0},
                        'extension_padding': {'type': 'float', 'min': 0.0, 'max': 1.0}
                    }
                }
            },
            'graph_generation': {
                'distance_threshold_symbols': {'type': 'int', 'min': 1},
                'distance_threshold_text': {'type': 'int', 'min': 1},
                'distance_threshold_lines': {'type': 'int', 'min': 1},
                'line_buffer': {'type': 'int', 'min': 0},
                'symbol_distance_threshold': {'type': 'int', 'min': 1},
                'symbol_overlap_threshold': {'type': 'float', 'min': 0.0, 'max': 1.0},
                'symbol_text_association_threshold': {'type': 'int', 'min': 1},
                'symbol_text_fallback_threshold': {'type': 'int', 'min': 1},
                'junction_detection_tolerance': {'type': 'float', 'min': 0.0},
                't_junction_endpoint_threshold': {'type': 'float', 'min': 0.0},
                'junction_clustering_radius': {'type': 'float', 'min': 0.0},
                'junction_angle_tolerance': {'type': 'float', 'min': 0.0, 'max': 180.0},
                'minimum_line_length': {'type': 'float', 'min': 0.0},
                'intersection_snap_distance': {'type': 'float', 'min': 0.0},
                'line_aberration_tolerance': {'type': 'float', 'min': 0.0},
                'junction_proximity_threshold': {'type': 'float', 'min': 0.0},
                'max_merge_iterations': {'type': 'int', 'min': 1, 'max': 20},
                'geometric_continuation_tolerance': {'type': 'float', 'min': 0.0},
                'component_filter': {
                    'type': 'dict',
                    'schema': {
                        'enabled': {'type': 'bool'},
                        'min_component_size': {'type': 'int', 'min': 1},
                        'max_line_density': {'type': 'float', 'min': 0.0, 'max': 1.0},
                        'min_symbol_density': {'type': 'float', 'min': 0.0, 'max': 1.0},
                        'max_notes_component_size': {'type': 'int', 'min': 1},
                        'frame_aspect_ratio_threshold': {'type': 'float', 'min': 0.0, 'max': 1.0},
                        'max_symbol_density_for_removal': {'type': 'float', 'min': 0.0, 'max': 1.0},
                        'extreme_symbol_density_threshold': {'type': 'float', 'min': 0.0, 'max': 1.0}
                    }
                }
            },
            'text_detection': {
                'timeout_seconds': {'type': 'int', 'min': 30, 'max': 900},
                'max_retries': {'type': 'int', 'min': 0, 'max': 10}
            },
            'symbol_detection': {
                'confidence_threshold': {'type': 'float', 'min': 0.0, 'max': 1.0},
                'nms_threshold': {'type': 'float', 'min': 0.0, 'max': 1.0}
            },
            'graph_visualization': {
                'output_format': {'type': 'str', 'allowed': ['png', 'jpg', 'svg']},
                'dpi': {'type': 'int', 'min': 72, 'max': 600},
                'line_width': {'type': 'int', 'min': 1, 'max': 10},
                'node_size': {'type': 'int', 'min': 1, 'max': 50}
            }
        }


# Convenience function for Lambda usage
def get_validated_config(stage: str, user_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Convenience function to get validated configuration for a processing stage.
    
    Args:
        stage: Processing stage name
        user_config: User-provided configuration overrides
        
    Returns:
        Validated and merged configuration
    """
    validator = ConfigValidator()
    return validator.get_merged_config(stage, user_config)
